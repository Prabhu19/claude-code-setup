#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""
Claude Code safety gate — blocks destructive commands before they run.

Installed as a PreToolUse hook. Reads JSON from stdin, exits 0 (allow) or 2 (block).
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any


def _match(pattern: str, cmd: str) -> bool:
    return bool(re.search(pattern, cmd, re.IGNORECASE | re.DOTALL))


def _check_rm_rf(cmd: str) -> tuple[bool, str]:
    """Block rm -rf only on critical paths; allow build artifacts like ./dist."""
    if not _match(r"\brm\s+-\S*[rR]\S*[fF]|\brm\s+-\S*[fF]\S*[rR]", cmd):
        return False, ""
    critical = _match(
        r"(?:^|\s)(?:"
        r"/(?:[^\s./]|\s|$)"  # absolute path (including bare /)
        r"|~/|~(?:\s|$)"  # home shorthand
        r"|\$(?:HOME|\{HOME\})"
        r"|\.git(?:/|\s|$)"
        r"|\.env(?:/|\s|$)"
        r"|\.ssh(?:/|\s|$)"
        r"|node_modules(?:/|\s|$)"
        r")",
        cmd,
    )
    if critical:
        return (
            True,
            "Destructive rm on a critical path (root, home, .git, .env, .ssh, node_modules).",
        )
    return False, ""


_COMPOUND_CHECKS = [_check_rm_rf]


_RULES: list[tuple[str, str]] = [
    # Git
    (
        # Matches
        # git push --force
        # git push origin main --force
        # git push -f
        # git push origin main -f
        # Skips: git push --force-with-lease | git push -foobar
        r"\bgit\s+push\b.*(?:--force(?!-with-lease)\b|(?<!\S)-f(?!\w))",
        "Force push is not allowed. Use --force-with-lease instead.",
    ),
    (
        # Matches
        # git reset --hard
        # git reset --hard HEAD
        # git reset --hard HEAD~3
        # Skips: git reset --soft HEAD | git reset HEAD~1
        r"\bgit\s+reset\s+--hard\b",
        "git reset --hard discards committed work and requires explicit user approval.",
    ),
    (
        # Matches
        # git clean -f
        # git clean -df
        # git clean -fdx
        # git clean -xf
        # Skips: git clean -n | git clean -i
        r"\bgit\s+clean\s+-\S*f",
        "git clean -f permanently deletes untracked files.",
    ),
    (
        # Matches
        # git checkout -- .
        # Skips: git checkout -- src/foo.py | git checkout main
        r"\bgit\s+checkout\s+--\s+\.",
        "git checkout -- . discards all working directory changes.",
    ),
    (
        # Matches
        # git restore .
        # Skips: git restore src/foo.py | git restore --staged .
        r"\bgit\s+restore\s+\.",
        "git restore . discards all working directory changes.",
    ),
    (
        # Matches
        # git branch -D feature-branch
        # git branch -D old-branch
        # Skips: git branch -d feature-branch (safe delete, checks merged)
        r"\bgit\s+branch\s+-D\b",
        "git branch -D force-deletes a branch without checking if it is merged.",
    ),
    (
        # Matches
        # git filter-branch --tree-filter '...' HEAD
        # git filter-repo --path src/
        # Skips: git log | git branch
        r"\bgit\s+filter-(?:branch|repo)\b",
        "History rewriting is destructive and requires explicit user approval.",
    ),
    (
        # Matches
        # git reflog expire --all
        # git reflog expire --expire=now --all
        # Skips: git reflog | git reflog show
        r"\bgit\s+reflog\s+expire\b",
        "Expiring the reflog is irreversible — recovery becomes impossible.",
    ),
    (
        # Matches
        # git gc --prune=now
        # git gc --aggressive --prune=now
        # Skips: git gc | git gc --prune=2.weeks.ago
        r"\bgit\s+gc\b.*--prune=now\b",
        "Aggressive GC with --prune=now discards unreachable objects immediately.",
    ),
    # File system
    (
        # Matches
        # dd if=disk.img of=/dev/sda
        # dd if=/dev/zero of=/dev/sdb
        # Skips: dd if=/dev/sda of=backup.img (reads from device, safe)
        r"\bdd\b.*\bof=/dev/",
        "Raw disk write (dd) can destroy data and requires explicit user approval.",
    ),
    (
        # Matches
        # mkfs.ext4 /dev/sdb1
        # mkfs -t xfs /dev/sda
        # Skips: (no common safe variant — all mkfs are blocked)
        r"\bmkfs\b",
        "Filesystem formatting requires explicit user approval.",
    ),
    (
        # Matches
        # echo foo > /etc/hosts
        # cat file > /usr/local/bin/script
        # Skips: echo foo > /tmp/file | echo foo > ./etc/custom
        r">\s*/(?:etc|bin|sbin|usr|lib|boot|dev)/",
        "Redirecting output into a system directory requires explicit user approval.",
    ),
    (
        # Matches
        # chmod 777 file.sh
        # chmod -R 777 /var/www
        # Skips: chmod 755 file.sh | chmod 644 config.json
        r"\bchmod\b.*\b777\b",
        "World-writable permissions (777) are a security risk.",
    ),
    (
        # Matches
        # chmod +s /usr/bin/script
        # chmod u+s binary
        # Skips: chmod +x script.sh | chmod g+w file
        r"\bchmod\b.*[+]s\b",
        "Setting the setuid/setgid bit requires explicit user approval.",
    ),
    (
        # Matches
        # chown -R root /
        # chown -R user /etc
        # Skips: chown -R user ./project | chown user file.txt
        r"\bchown\s+-R\b.*\s+/",
        "Recursive chown from root requires explicit user approval.",
    ),
    (
        # Matches
        # shred -u .env
        # shred id_rsa
        # shred credentials.json
        # Skips: shred tempfile.txt
        r"\bshred\b.*(?:\.env|id_rsa|credentials|secrets?)\b",
        "Securely deleting credentials requires explicit user approval.",
    ),
    # Network / supply-chain
    (
        # Matches
        # curl https://example.com/install.sh | bash
        # wget -qO- https://get.tool.io | sh
        # curl https://example.com/setup.py | python3
        # Skips: curl https://example.com/file.txt | grep foo
        r"(?:curl|wget)\b.*\|\s*(?:sudo\s+)?(?:bash|sh|zsh|fish|python3?|node|ruby|perl)\b",
        "Piping a download to a shell/interpreter is a supply-chain risk. Download and inspect first.",
    ),
    (
        # Matches
        # bash <(curl https://example.com/script.sh)
        # sh <(wget -qO- https://example.com/run.sh)
        # Skips: bash script.sh | bash <(echo 'echo hi')
        r"(?:bash|sh|zsh)\s*<\s*\(\s*(?:curl|wget)\b",
        "Process-substituting a download into a shell is a supply-chain risk.",
    ),
    (
        # Matches
        # eval $(curl https://example.com/env.sh)
        # eval $(wget -qO- https://example.com/setup.sh)
        # Skips: eval "echo hello" | eval $(git rev-parse HEAD)
        r"\beval\b.*\$\((?:curl|wget)\b",
        "eval-ing a download is a supply-chain risk.",
    ),
    (
        # Matches
        # source <(curl https://example.com/env.sh)
        # source <(wget -qO- https://example.com/config.sh)
        # Skips: source .env | source <(echo 'export FOO=bar')
        r"\bsource\b.*<\s*\(\s*(?:curl|wget)\b",
        "Sourcing a download is a supply-chain risk.",
    ),
    # SQL
    (
        # Matches
        # DROP TABLE users
        # DROP DATABASE mydb
        # DROP SCHEMA public
        # Skips: DROP INDEX idx_name | SELECT * FROM table
        r"\bDROP\s+(?:TABLE|DATABASE|SCHEMA|TABLESPACE)\b",
        "Destructive SQL (DROP) requires explicit user approval.",
    ),
    (
        # Matches
        # TRUNCATE TABLE users
        # TRUNCATE orders
        # Skips: DELETE FROM users WHERE id=1 | SELECT COUNT(*) FROM users
        r"\bTRUNCATE\s+(?:TABLE\s+)?\w+",
        "TRUNCATE deletes all rows and requires explicit user approval.",
    ),
    (
        # Matches
        # DELETE FROM users;
        # DELETE FROM orders
        # Skips: DELETE FROM users WHERE id=1
        r"\bDELETE\s+FROM\s+\w+\s*(?:;|$)",
        "DELETE without a WHERE clause deletes all rows — requires explicit user approval.",
    ),
    (
        # Matches
        # ALTER TABLE users DROP COLUMN email
        # ALTER TABLE orders DROP COLUMN legacy_id
        # Skips: ALTER TABLE users ADD COLUMN phone TEXT | ALTER TABLE users RENAME COLUMN name TO full_name
        r"\bALTER\s+TABLE\b.*\bDROP\s+COLUMN\b",
        "Dropping a column is irreversible without a prior backup.",
    ),
    # MongoDB
    (
        # Matches
        # db.dropDatabase()
        # Skips: db.getCollectionNames() | db.stats()
        r"\bdb\.dropDatabase\(\)",
        "MongoDB dropDatabase destroys the entire database.",
    ),
    (
        # Matches
        # collection.drop()
        # db.collection.drop()
        # Skips: collection.find() | collection.deleteOne({})
        r"\bcollection\b.*\.drop\(\)",
        "MongoDB collection.drop() destroys all documents in the collection.",
    ),
    # Redis
    (
        # Matches
        # FLUSHALL
        # FLUSHDB
        # Skips: KEYS * | DEL mykey
        r"\b(?:FLUSHALL|FLUSHDB)\b",
        "Redis FLUSHALL/FLUSHDB wipes all data and requires explicit user approval.",
    ),
    (
        # Matches
        # CONFIG REWRITE
        # Skips: CONFIG GET maxmemory | CONFIG SET maxmemory 100mb
        r"\bCONFIG\s+REWRITE\b",
        "Redis CONFIG REWRITE modifies the server config file in place.",
    ),
    # Elasticsearch
    (
        # Matches
        # DELETE /my-index
        # DELETE /logs-2024
        # Skips: DELETE /my-index/_doc/1 (deletes a single document, not the index)
        r"DELETE\s+/[^/\s]+\s*$",
        "Deleting an Elasticsearch index requires explicit user approval.",
    ),
    # Docker
    (
        # Matches
        # docker system prune
        # docker system prune -af
        # Skips: docker system df | docker system info
        r"\bdocker\s+system\s+prune\b",
        "docker system prune removes unused Docker resources.",
    ),
    (
        # Matches
        # docker rm $(docker ps -aq)
        # docker remove $(docker ps -aq --filter status=exited)
        # Skips: docker rm mycontainer (literal name, no subshell)
        r"\bdocker\s+(?:rm|remove)\b.*\$\(",
        "Bulk container removal requires explicit user approval.",
    ),
    (
        # Matches
        # docker volume rm $(docker volume ls -q)
        # Skips: docker volume rm myvolume (literal name, no subshell)
        r"\bdocker\s+volume\s+rm\b.*\$\(",
        "Bulk volume removal requires explicit user approval.",
    ),
    (
        # Matches
        # docker network rm $(docker network ls -q)
        # Skips: docker network rm mynetwork (literal name, no subshell)
        r"\bdocker\s+network\s+rm\b.*\$\(",
        "Bulk network removal requires explicit user approval.",
    ),
    # Kubernetes
    (
        # Matches
        # kubectl delete pods --all
        # kubectl delete deployments --all -n production
        # Skips: kubectl delete pod mypod (targets a specific resource)
        r"\bkubectl\s+delete\b.*--all\b",
        "kubectl delete --all destroys all resources in the namespace.",
    ),
    (
        # Matches
        # kubectl delete namespace staging
        # kubectl delete ns production
        # Skips: kubectl delete pod mypod | kubectl get namespace
        r"\bkubectl\s+delete\s+(?:namespace|ns)\b",
        "Deleting a Kubernetes namespace destroys all resources inside it.",
    ),
    (
        # Matches
        # kubectl delete pv pv-name
        # kubectl delete pv --all
        # Skips: kubectl get pv | kubectl describe pv pv-name
        r"\bkubectl\s+delete\s+pv\b",
        "Deleting Persistent Volumes may cause irreversible data loss.",
    ),
    (
        # Matches
        # kubectl drain node-1
        # kubectl drain node-1 --ignore-daemonsets
        # Skips: kubectl cordon node-1 | kubectl get nodes
        r"\bkubectl\s+drain\b",
        "kubectl drain evicts all pods from a node — requires explicit user approval.",
    ),
    # Terraform / OpenTofu
    (
        # Matches
        # terraform destroy
        # terraform destroy -auto-approve
        # tofu destroy
        # Skips: terraform plan | terraform apply
        r"\bterraform\s+destroy\b|\btofu\s+destroy\b",
        "terraform/tofu destroy tears down real infrastructure.",
    ),
    (
        # Matches
        # terraform state rm aws_instance.web
        # tofu state rm module.vpc
        # Skips: terraform state list | terraform state show
        r"\bterraform\s+state\s+rm\b|\btofu\s+state\s+rm\b",
        "Removing Terraform state loses track of managed resources.",
    ),
    # AWS CLI
    (
        # Matches
        # aws s3 rm s3://my-bucket/ --recursive
        # aws s3 rm s3://my-bucket/folder --recursive
        # Skips: aws s3 rm s3://my-bucket/file.txt (single file, no --recursive)
        r"\baws\s+s3\b.*\brm\b.*--recursive\b",
        "Recursive S3 delete requires explicit user approval.",
    ),
    (
        # Matches
        # aws s3 sync . s3://my-bucket --delete
        # aws s3 sync s3://src s3://dst --delete
        # Skips: aws s3 sync . s3://my-bucket (without --delete)
        r"\baws\s+s3\b.*sync.*--delete\b",
        "s3 sync --delete removes objects not present in the source.",
    ),
    (
        # Matches
        # aws ec2 terminate-instances --instance-ids i-1234567890abcdef0
        # Skips: aws ec2 stop-instances | aws ec2 describe-instances
        r"\baws\s+ec2\s+terminate-instances\b",
        "EC2 instance termination is irreversible.",
    ),
    (
        # Matches
        # aws rds delete-db-instance --db-instance-identifier mydb
        # Skips: aws rds stop-db-instance | aws rds describe-db-instances
        r"\baws\s+rds\s+delete-db-instance\b",
        "Deleting an RDS instance may destroy its data.",
    ),
    (
        # Matches
        # aws lambda delete-function --function-name my-function
        # Skips: aws lambda get-function | aws lambda list-functions
        r"\baws\s+lambda\s+delete-function\b",
        "Deleting a Lambda function requires explicit user approval.",
    ),
    # GCP
    (
        # Matches
        # gcloud projects delete my-project
        # gcloud sql delete my-instance
        # gcloud compute delete my-vm
        # gcloud container delete my-cluster
        # Skips: gcloud projects list | gcloud compute describe
        r"\bgcloud\s+(?:projects?|sql|compute|container)\s+delete\b",
        "GCP resource deletion requires explicit user approval.",
    ),
    # Heroku
    (
        # Matches
        # heroku apps:destroy myapp
        # heroku app:destroy --app myapp
        # Skips: heroku apps | heroku apps:info
        r"\bheroku\s+apps?:destroy\b",
        "Heroku app destruction is irreversible.",
    ),
    # Privilege escalation
    (
        # Matches
        # sudo rm -rf /var
        # sudo dd if=/dev/zero of=/dev/sda
        # sudo mkfs.ext4 /dev/sdb
        # sudo chmod 777 /etc/passwd
        # Skips: sudo apt install | sudo systemctl restart nginx
        r"\bsudo\s+(?:rm\s+-\S*[rR]|dd\b|mkfs\b|chmod\s+777\b)",
        "Privileged destructive command requires explicit user approval.",
    ),
    (
        # Matches
        # visudo
        # Skips: (no common safe variant — all visudo are blocked)
        r"\bvisudo\b",
        "Editing sudoers requires explicit user approval.",
    ),
    # Shell
    (
        # Matches
        # :(){ :|:& };:
        # Skips: (no benign command matches this pattern)
        r":\(\)\{.*\|.*:.*\}",
        "Fork bomb pattern detected.",
    ),
    (
        # Matches
        # eval $(cat script.sh)
        # eval $(generate-config)
        # Skips: eval "echo hello" | eval "$MY_VAR"
        r"\beval\b\s+\$\(",
        "eval with command substitution is an arbitrary code execution risk.",
    ),
    # System
    (
        # Matches
        # kill -9 1
        # kill -9 -1
        # Skips: kill -9 12345 | kill -15 1
        r"\bkill\s+-9\s+-?1\b",
        "Sending SIGKILL to PID 1 terminates all processes on the system.",
    ),
    (
        # Matches
        # crontab -r
        # Skips: crontab -l | crontab -e
        r"\bcrontab\s+-r\b",
        "crontab -r removes all scheduled cron jobs.",
    ),
    (
        # Matches
        # systemctl stop ssh
        # systemctl disable ufw
        # systemctl mask networking
        # Skips: systemctl stop nginx | systemctl restart apache2
        r"\bsystemctl\s+(?:stop|disable|mask)\s+(?:ssh|sshd|networking|network-manager|firewall|ufw|iptables|nftables)\b",
        "Disabling a critical system service requires explicit user approval.",
    ),
]


def main() -> None:
    try:
        hook_input: dict[str, Any] = json.loads(sys.stdin.readline())
        cmd: str = (
            hook_input.get("tool_input", {}).get("command") or hook_input.get("command") or ""
        )
    except (json.JSONDecodeError, AttributeError):
        sys.exit(0)

    if not cmd.strip():
        sys.exit(0)

    for check in _COMPOUND_CHECKS:
        blocked, message = check(cmd)
        if blocked:
            print(f"⛔ BLOCKED: {message}")
            sys.exit(2)

    for pattern, message in _RULES:
        if _match(pattern, cmd):
            print(f"⛔ BLOCKED: {message}")
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()

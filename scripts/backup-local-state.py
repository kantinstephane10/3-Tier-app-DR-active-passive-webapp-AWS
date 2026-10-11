import datetime,json,os,shutil,sys
from pathlib import Path
base=Path(sys.argv[1])
if not base.is_dir():
    raise SystemExit('Local state directory does not exist; run prepare-local-state.sh on this agent.')
state=base/'infrastructure.tfstate'
if not state.is_file():
    print('No workload state file yet; no backup created.')
    raise SystemExit(0)
json.loads(state.read_text())
backup_dir=base/'backups'
backup_dir.mkdir(mode=0o700,exist_ok=True)
os.chmod(state,0o600)
name=datetime.datetime.now(datetime.timezone.utc).strftime('infrastructure-%Y%m%dT%H%M%S%fZ.tfstate')
copy=backup_dir/name
shutil.copyfile(state,copy)
os.chmod(copy,0o600)
marker=base/'state-created'
marker.touch(mode=0o600,exist_ok=True)
for old in sorted(backup_dir.glob('infrastructure-*.tfstate'))[:-20]:
    old.unlink()
print('Persistent local state backed up on this Jenkins agent.')

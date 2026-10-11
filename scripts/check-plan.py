import json,sys
plan=json.load(open(sys.argv[1]))
deletes=[r['address'] for r in plan.get('resource_changes',[]) if 'delete' in r['change']['actions']]
if deletes:
    print('Deployment halted: this plan deletes or replaces resources. Review the desired stage and migrations. Addresses:')
    print('\n'.join(deletes))
    sys.exit(1)
print('Plan check passed: no resource deletions or replacements.')

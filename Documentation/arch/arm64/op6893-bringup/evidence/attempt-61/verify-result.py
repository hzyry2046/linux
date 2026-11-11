import json, pathlib, re
p = pathlib.Path(__file__).parent
s = (p / 'cycle.txt').read_text()
trace = {}
for line in s.splitlines():
    if line.startswith('point='):
        fields = dict(v.split('=', 1) for v in line.split())
        point = fields.pop('point')
        trace[point] = {k: int(v, 0) for k, v in fields.items()}
assert len(trace) == 7
points = list(trace.values())
assert all(a['ns'] < b['ns'] for a, b in zip(points, points[1:]))
for name in ('before-release', 'after-release14', 'after-release-bank2', 'after-release13'):
    t = trace[name]
    assert not t['request'] & 0x6000 and not t['request2'] & 4
    assert not t['sta1'] & 0x6000 and not t['sta21'] & 4
    assert t['power'] & 2 and t['power2'] & 2 and t['control'] == 13 and t['host'] == 1
settle = trace['after-settle']
assert not settle['request'] & 0x6000 and settle['sta1'] & 0x6000 == 0x4000
assert not settle['request2'] & 4 and not settle['sta21'] & 4
assert 'id_read=0' in s and 'domain_cleanup_result=0' in s
assert 'rail_refs=0,0 dirty=0,0 uncertain_enable=0' in s
assert 'result=-16 cleanup_result=0' in s
repeat = (p / 'repeat.txt').read_text()
hashes = re.findall(r'^([a-f0-9]{64})  /sys/', repeat, re.M)
assert len(hashes) == 2 and hashes[0] == hashes[1] and 'repeat_refused' in repeat
reg_path = p / 'regression.txt'
if not reg_path.exists():
    reg_path = p / 'regression-summary.txt'
reg = reg_path.read_text()
assert '\n0-7\n1\n' in reg
assert 'e0b83ec5203e2a77126d84dee4b1c297d17263ff331ed2b3d5b9099973274f80  /dev/sdc48' in reg
assert '4b831520cce5df878a6ddb1b428c235d1735f5eea9fe5148f0fa6d0783f90051' in reg
out = {'image': '764614420260', 'trace_points': len(trace),
       'after_release_to_settle_ns': settle['ns'] - trace['after-release13']['ns'],
       'bit14_ack_reappeared_with_request_clear': True,
       'id_read': False, 'domain_cleanup_result': 0, 'rail_cleanup_result': 0,
       'repeat_refused_trace_unchanged': True, 'boot_root_hashes_match': True}
(p / 'verified.json').write_text(json.dumps(out, indent=2) + '\n')
print(json.dumps(out, indent=2))

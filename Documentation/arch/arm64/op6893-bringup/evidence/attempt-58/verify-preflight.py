#!/usr/bin/env python3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import re
import subprocess

root = Path('/data/src/mainline/mt6893-direct')
ssh = ['sudo', 'ip', 'netns', 'exec', 'op6893-native', 'ssh', '-i', str(root/'ssh/id_ed25519'), '-o', 'ConnectTimeout=10', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile='+str(root/'ssh/known_hosts'), 'root@192.0.2.2']
cmd = 'set -eu; test "$(uname -r)" = "7.3.0-op6893-d1-d79c36ef9d28+"; cat /sys/devices/platform/conn-preflight/preflight'

def capture(index):
    output = subprocess.check_output(ssh+[cmd], text=True, timeout=30)
    values = dict(re.findall(r'([\w\[\]]+)=(\S+)', output))
    assert values['off_at_both_samples']=='1'
    assert values['rc_mode']=='1' and values['legacy_protection_complete']=='0'
    assert values['activation_ready']=='0' and values['upstream_policy']=='unresolved'
    assert values['dark_conn_access']=='none' and int(values['host'],0)==0
    assert values['status']==values['end_status'] and values['status2']==values['end_status2']
    assert int(values['control'],0)==int(values['end_control'],0)==0x12
    assert int(values['start_ns']) < int(values['end_ns'])
    pmic = {int(a,16):int(v,16) for a,v in re.findall(r'pmic\[(0x[0-9a-f]+)\]=(0x[0-9a-f]+)', output)}
    assert len(pmic)==20 and pmic[8]==0x5930
    for reg in [0x1c1c,0x1c20,0x1c2e,0x1c32,0x1be2,0x1be6,0x1c08,0x1c0c]:
        assert pmic[reg]==0
    rails = {n:(int(e),int(v)) for n,e,v in re.findall(r'rail=(\S+) enabled=(\d+) nominal_uv=(\d+)',output)}
    assert len(rails)==6 and rails['vs1']==(1,2000000) and rails['vs2']==(1,1400000)
    for n,v in [('vcn13',1300000),('vcn18',1800000),('vcn33-1',3500000),('vcn33-2',3500000)]:
        assert rails[n]==(0,v)
    (Path(__file__).parent/f'preflight-{index:02}.txt').write_text(output)
    return {'index':index,'start_ns':int(values['start_ns']),'end_ns':int(values['end_ns']), 'rc':values['rc'],'host':values['host'],'pmic':{hex(k):hex(v) for k,v in pmic.items()},'rails':rails}

results = [capture(i) for i in range(16)]
with ThreadPoolExecutor(max_workers=4) as executor:
    results += list(executor.map(capture, range(16,20)))
ordered = sorted(results, key=lambda r:r['start_ns'])
assert all(a['end_ns'] <= b['start_ns'] for a,b in zip(ordered, ordered[1:]))
print(json.dumps({'release':'7.3.0-op6893-d1-d79c36ef9d28+', 'sequential':16,'concurrent':4,'serialized_intervals':True,'all_checks_passed':True,'captures':results,'limits':['Only selected sequential registers, no power transition or physical voltage measurement.','Real leaf handles do not establish managed upstream supply ownership.']},indent=2))

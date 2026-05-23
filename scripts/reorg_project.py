from pathlib import Path
import shutil

base = Path('.')

for d in ['docs', 'outputs', '.swarm']:
    Path(d).mkdir(exist_ok=True)

for p in ['agent2_rtl', 'agent3_dv', 'agent4_physical', 'agent5_formal']:
    d = Path('semiconductor_swarm/agents') / p
    d.mkdir(exist_ok=True)
    init = d / '__init__.py'
    if not init.exists():
        init.write_text('"""Agent package."""\n', encoding='utf-8')

for f in base.glob('*.md'):
    if f.name != 'README.md':
        shutil.move(str(f), str(Path('docs') / f.name))

move_map = {
    'semiconductor_swarm/agents/rtl_designer.py': 'semiconductor_swarm/agents/agent2_rtl/rtl_designer.py',
    'semiconductor_swarm/agents/agent2_prompt.py': 'semiconductor_swarm/agents/agent2_rtl/agent2_prompt.py',
    'semiconductor_swarm/agents/dv_engineer.py': 'semiconductor_swarm/agents/agent3_dv/dv_engineer.py',
    'semiconductor_swarm/agents/agent3_prompt.py': 'semiconductor_swarm/agents/agent3_dv/agent3_prompt.py',
    'semiconductor_swarm/agents/physical_designer.py': 'semiconductor_swarm/agents/agent4_physical/physical_designer.py',
    'semiconductor_swarm/agents/agent4_prompt.py': 'semiconductor_swarm/agents/agent4_physical/agent4_prompt.py',
    'semiconductor_swarm/agents/formal_verifier.py': 'semiconductor_swarm/agents/agent5_formal/formal_verifier.py',
    'semiconductor_swarm/agents/agent5_prompt.py': 'semiconductor_swarm/agents/agent5_formal/agent5_prompt.py',
}
for s, d in move_map.items():
    sp, dp = Path(s), Path(d)
    if sp.exists():
        shutil.move(str(sp), str(dp))

for f in ['agent1_architect.py', 'agent2_rtl_designer.py', 'agent3_dv_engineer.py', 'agent4_physical_designer.py', 'agent5_formal_verifier.py']:
    p = Path(f)
    if p.exists():
        p.unlink()

for d in ['swarm_out', 'proof_run_thermal_sensor']:
    p = Path(d)
    if p.exists():
        shutil.move(str(p), str(Path('outputs') / p.name))

for p in list(base.iterdir()):
    if p.is_dir() and (p.name.startswith('swarm_bat_demo_') or p.name.startswith('swarm_ux_demo_') or p.name in {'generated_rtl', 'generated_fpga', 'generated_formal', 'tmp_smoke'}):
        shutil.rmtree(p)

for p in list(base.iterdir()):
    if p.is_file() and ((p.name.startswith('ux_demo_') and p.suffix == '.txt') or (p.name.startswith('bat_demo_') and p.suffix == '.txt')):
        p.unlink()

for p in base.glob('*.json'):
    if p.name not in {'codex_api.local.json', 'codex_api.example.json'}:
        p.unlink()

for f in ['swarm_checkpoints.sqlite', 'status.log']:
    p = Path(f)
    if p.exists():
        shutil.move(str(p), str(Path('.swarm') / p.name))

repls = {
    'semiconductor_swarm.agents.agent2_rtl.rtl_designer': 'semiconductor_swarm.agents.agent2_rtl.rtl_designer',
    'semiconductor_swarm.agents.agent2_rtl.agent2_prompt': 'semiconductor_swarm.agents.agent2_rtl.agent2_prompt',
    'semiconductor_swarm.agents.agent3_dv.dv_engineer': 'semiconductor_swarm.agents.agent3_dv.dv_engineer',
    'semiconductor_swarm.agents.agent3_dv.agent3_prompt': 'semiconductor_swarm.agents.agent3_dv.agent3_prompt',
    'semiconductor_swarm.agents.agent4_physical.physical_designer': 'semiconductor_swarm.agents.agent4_physical.physical_designer',
    'semiconductor_swarm.agents.agent4_physical.agent4_prompt': 'semiconductor_swarm.agents.agent4_physical.agent4_prompt',
    'semiconductor_swarm.agents.agent5_formal.formal_verifier': 'semiconductor_swarm.agents.agent5_formal.formal_verifier',
    'semiconductor_swarm.agents.agent5_formal.agent5_prompt': 'semiconductor_swarm.agents.agent5_formal.agent5_prompt',
}
for path in base.rglob('*.py'):
    if any(part in {'.git', '__pycache__'} for part in path.parts):
        continue
    text = path.read_text(encoding='utf-8')
    new = text
    for old, newval in repls.items():
        new = new.replace(old, newval)
    if new != text:
        path.write_text(new, encoding='utf-8')
        print('updated', path)

print('cleanup_done')
import ast,pathlib,collections
root=pathlib.Path(__file__).resolve().parents[1]
fields=set('distance position heading speed length width brain _claimed_movement _merge_entry_speed state wait_reason desired_speed stopped_elapsed signal_intent phantom_target route points controlled_movements route_segments id color appearance source_type speed_cap_mph'.split())
for p in sorted(root.rglob('*.py')):
 if any(x in p.parts for x in ('build','__pycache__','.git')): continue
 try: tree=ast.parse(p.read_text())
 except (SyntaxError,UnicodeDecodeError): continue
 for n in ast.walk(tree):
  targets=[]
  if isinstance(n,(ast.Assign,ast.AnnAssign,ast.AugAssign,ast.NamedExpr)): targets=n.targets if isinstance(n,ast.Assign) else [n.target]
  for target in targets:
   for t in ast.walk(target):
    if isinstance(t,ast.Attribute) and t.attr in fields:
     print(f'{p.relative_to(root)}:{t.lineno}: {ast.unparse(t)}')
  if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='setattr' and len(n.args)>=2:
   print(f'{p.relative_to(root)}:{n.lineno}: dynamic {ast.unparse(n)}')

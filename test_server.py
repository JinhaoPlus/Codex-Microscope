from contextlib import closing
import unittest,tempfile,json
from pathlib import Path
from server import history,category
class Records(unittest.TestCase):
 def test_workspace_names_require_explicit_unambiguous_roots(self):
  from unittest.mock import patch
  import server
  with tempfile.TemporaryDirectory() as d,patch.object(server,'HOME',Path(d)):
   path=Path(d)/'.codex-global-state.json'
   self.assertEqual(server.workspace_names(),{})
   projects={
    'a':{'name':'Display name','rootPaths':['/work/project/','/other/root']},
    'b':{'name':'Other name','rootPaths':['/other/root']},
    'c':{'name':'Display name','rootPaths':['/work/project']},
    'bad':{'name':12,'rootPaths':['/work/bad']},
    'empty':{'name':' ','rootPaths':['/work/empty']},
    'shape':{'name':'Wrong shape','rootPaths':'/work/wrong'},
   }
   path.write_text(json.dumps({'local-projects':projects}))
   self.assertEqual(server.workspace_names(),{'/work/project':'Display name'})
   with patch.object(server,'read_sql',return_value=[dict(cwd='/work/project/'),dict(cwd='/work/project/child'),dict(cwd='/home/example'),dict(cwd=None)]):
    (Path(d)/'state_1.sqlite').touch()
    self.assertEqual([r['workspace_name'] for r in server.rows()],['Display name',None,None,None])
   for content in ('broken','[]','{"local-projects":[]}'):
    path.write_text(content)
    self.assertEqual(server.workspace_names(),{})
 def test_tool_pair_and_partial_line(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'r.jsonl';p.write_text('\n'.join(json.dumps({'type':'response_item','payload':x}) for x in [{'type':'message','role':'user','content':[{'type':'input_text','text':'hello'}]},{'type':'custom_tool_call','name':'exec','input':'code','call_id':'a'},{'type':'custom_tool_call_output','call_id':'a','output':[{'type':'input_text','text':'result'}]}])+'\n{"unfinished":')
   items,bad=history(p);self.assertEqual(len(items),2);self.assertEqual(items[1]['output'],'result');self.assertEqual(bad,1)
 def test_latest_status_replaces_previous_failure(self):
  import sqlite3
  from unittest.mock import patch
  import server
  with tempfile.TemporaryDirectory() as d:
   with closing(sqlite3.connect(Path(d)/'thread_history_1.sqlite')) as c, c:
    c.execute('create table thread_turns(thread_id text,status text,rollout_ordinal integer)')
    c.executemany('insert into thread_turns values(?,?,?)',[('a','failed',1),('a','completed',2),('b','inProgress',3),('c','failed',4)])
   with patch.object(server,'HOME',Path(d)):
    self.assertEqual(server.latest_statuses(),{'a':'completed','b':'inProgress','c':'failed'})
 def test_model_history_is_per_turn(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'r.jsonl';events=[]
   for turn,model,effort in [('t1','model-a','medium'),('t2','model-b','high'),('t3',None,None)]:
    events.extend([{'type':'turn_context','timestamp':'2026-11-04T01:00:00Z','payload':{'turn_id':turn,'model':model,'effort':effort}},{'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'hello'}]}}])
   p.write_text('\n'.join(map(json.dumps,events)))
   items,_=history(p)
   self.assertEqual([x['turn_context']['model'] for x in items],['model-a','model-b',None])
   self.assertEqual([x['turn_context']['effort'] for x in items],['medium','high',None])
 def test_sources(self):
  for s,o,want in [('exec','codex_exec','exec'),('vscode','Codex Desktop','app'),('cli','codex_cli','cli'),('{"subagent":{}}','','agent')]:self.assertEqual(category({'source':s,'originator':o}),want)
if __name__=='__main__':unittest.main()

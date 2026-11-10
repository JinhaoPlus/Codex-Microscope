from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server


def record(kind,payload):
    return json.dumps(dict(type=kind,payload=payload))+'\n'


class NativeTools(unittest.TestCase):
    def test_each_native_command_retains_its_own_output_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'outputs.jsonl'
            content=record('turn_context',dict(turn_id='t'))+record('response_item',dict(type='custom_tool_call',name='exec',call_id='batch',input='cat a.py; cat b.py'))
            for key in ('a','b'):
                content+=record('event_msg',dict(type='item_completed',turn_id='t',item=dict(type='CommandExecution',id=key,command=['/bin/sh','-c','cat '+key+'.py'],cwd='/project',status='completed',exit_code=0,aggregated_output=key+' file contents',parsed_cmd=[dict(type='read',cmd='cat '+key+'.py',path=key+'.py')])))
            path.write_text(content)
            items,_=server.history(path)
            self.assertEqual([action['result_index'] for action in items[0]['native_actions']],[0,1])
            self.assertEqual([source['output'] for source in items[0]['native_results']],['a file contents','b file contents'])
            self.assertEqual(items[0]['native_results'][0]['cwd'],'/project')
            self.assertNotIn('native_results',server.page_payload(items,{})['items'][0])
            self.assertEqual(server.page_payload(items,{'item':['0']})['item']['native_results'][1]['exit_code'],0)

    def test_native_patch_is_edit_with_exact_counts_and_no_duplicate(self):
        diff='--- a/server.py\n+++ b/server.py\n@@ -1 +1,2 @@\n-old\n+new\n+++ counter\n'
        native=dict(type='item_completed',turn_id='t',item=dict(type='FileChange',id='patch-id',changes={'server.py':dict(type='update',unified_diff=diff)}))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'patch.jsonl'
            path.write_text(record('turn_context',dict(turn_id='t'))+
                record('response_item',dict(type='custom_tool_call',name='exec',call_id='patch',input='text(await tools.apply_patch("*** Update File: server.py"))'))+
                record('event_msg',native)*2+
                record('response_item',dict(type='custom_tool_call_output',call_id='patch',output='patch output')))
            items,_=server.history(path)
            self.assertEqual(items[0]['native_actions'],[dict(type='edit',path='server.py',name='server.py',additions=2,deletions=1,diff=diff,result_index=0)])
            preview=server.page_payload(items,{})['items'][0]
            self.assertNotIn('native_actions',preview)
            self.assertNotIn('native_results',preview)
            self.assertEqual(items[0]['output'],'patch output')

    def test_file_change_database_shape_preserves_counts_and_unknown_counts(self):
        actions=server.native_file_actions(dict(changes=[dict(path='a.py',diff='@@\n+added\n-removed\n'),dict(path='b.py')]))
        self.assertEqual(actions[0],dict(type='edit',path='a.py',name='a.py',additions=1,deletions=1,diff='@@\n+added\n-removed\n'))
        self.assertNotIn('additions',actions[1])

    def test_rollout_native_actions_attach_once_to_the_enclosing_call(self):
        command="cat /skills/animate/SKILL.md; rg -n 'a;b' app.js"
        actions=[dict(type='read',cmd='cat /skills/animate/SKILL.md',name='SKILL.md',path='/skills/animate/SKILL.md'),
                 dict(type='search',query='a;b',path='app.js',cmd="rg -n 'a;b' app.js")]
        native=dict(type='item_completed',turn_id='t',item=dict(type='CommandExecution',id='exec-a',command=['/bin/zsh','-lc',command],parsed_cmd=actions))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'native.jsonl'
            path.write_text(record('turn_context',dict(turn_id='t'))+
                record('response_item',dict(type='custom_tool_call',name='exec',call_id='call',input='await tools.exec_command({cmd:'+json.dumps(command)+'})'))+
                record('event_msg',native)*2+
                record('response_item',dict(type='custom_tool_call_output',call_id='call',output='original output')))
            items,_=server.history(path)
            self.assertEqual(len(items),1)
            self.assertEqual(items[0]['native_actions'],[{**action,'result_index':0} for action in actions])
            self.assertEqual(items[0]['output'],'original output')
            preview=server.page_payload(items,{})['items'][0]
            self.assertNotIn('native_actions',preview)
            self.assertNotIn('native_results',preview)
            self.assertNotIn('output',preview)
            self.assertEqual(server.page_payload(items,{'item':['0']})['item']['output'],'original output')

    def test_parallel_commands_match_input_and_ambiguous_events_are_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'parallel.jsonl'
            content=record('turn_context',dict(turn_id='t'))
            for key in ('a','b'):
                content+=record('response_item',dict(type='function_call',name='exec_command',call_id=key,arguments=json.dumps({'cmd':'cat '+key})))
            for key in ('b','a','unrelated'):
                content+=record('event_msg',dict(type='item_completed',turn_id='t',item=dict(type='CommandExecution',id=key,command=['/bin/sh','-c','cat '+key],parsed_cmd=[dict(type='read',path=key)])))
            path.write_text(content)
            items,_=server.history(path)
            self.assertEqual([item['native_actions'] for item in items[:2]],[[dict(type='read',path='a',result_index=0)],[dict(type='read',path='b',result_index=0)]])
            self.assertTrue(items[2]['standalone_native'])
            self.assertEqual(items[2]['operations'][0]['summary'], '执行结果 cat unrelated')

    def test_database_fallback_preserves_command_actions(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'HOME',Path(directory)):
            item=dict(type='commandExecution',command='cat sample.md',aggregatedOutput='body',commandActions=[dict(type='read',name='sample.md',path='sample.md')])
            with closing(sqlite3.connect(Path(directory)/'thread_history_1.sqlite')) as connection, connection:
                connection.execute('create table thread_items(thread_id text,item_json text,created_at_ms integer,turn_id text,rollout_ordinal integer)')
                connection.execute('insert into thread_items values(?,?,?,?,?)',('t',json.dumps(item),1,'turn',0))
            parsed=server.stored_history('t')[0]
            self.assertEqual(parsed['native_actions'],[{**action,'result_index':0} for action in item['commandActions']])
            self.assertEqual(parsed['output'],'body')

    def test_standalone_command_and_patch_have_same_projection_in_both_sources(self):
        from contextlib import nullcontext
        command="sed -n '3p' readme; find docs -type f"
        actions=[dict(type='read',cmd="sed -n '3p' readme",path='readme'),
                 dict(type='list_files',cmd='find docs -type f',path='docs')]
        diff='@@ -1 +1 @@\n-old\n+new'
        body='+actual file contents\n-actual file contents\n'
        records=[dict(type='CommandExecution',command=['sh','-c',command],source='unified_exec_startup',
                      status='completed',aggregated_output='one shared output',parsed_cmd=actions),
                 dict(type='FileChange',status='completed',changes={
                     'one':dict(type='add',content=body),'two':dict(type='delete',content=body),
                     'old':dict(type='update',move_path='renamed',unified_diff=diff)})]
        db_records=[dict(type='commandExecution',command=command,source='unifiedExecStartup',status='completed',
                         aggregatedOutput='one shared output',commandActions=[
                             dict(type='read',command=actions[0]['cmd'],path='readme'),
                             dict(type='listFiles',command=actions[1]['cmd'],path='docs')]),
                    dict(type='fileChange',status='completed',changes=[
                        dict(path='one',kind=dict(type='add'),diff=body),dict(path='two',kind=dict(type='delete'),diff=body),
                        dict(path='old',kind=dict(type='update',movePath='renamed'),diff=diff+'\n\nMoved to: renamed')])]
        rollout=server.parse_rollout(nullcontext([record('event_msg',dict(type='item_completed',item=item)) for item in records]))[0]
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'HOME',Path(directory)):
            with closing(sqlite3.connect(Path(directory)/'thread_history_1.sqlite')) as db:
                db.execute('create table thread_items(thread_id text,item_json text,created_at_ms integer,turn_id text,rollout_ordinal integer)')
                db.executemany('insert into thread_items values(?,?,?,?,?)',[('t',json.dumps(it),1,'turn',i) for i,it in enumerate(db_records)])
                db.commit()
            db_items=server.stored_history('t')
        self.assertEqual(len(rollout),len(db_items))
        for left,right in zip(rollout,db_items):
            self.assertEqual(left['native_actions'],right['native_actions'])
            self.assertEqual(left['exec_view'],right['exec_view'])
            self.assertEqual(left['native_results'],right['native_results'])
        self.assertEqual(rollout[0]['exec_view']['label'],'读取 readme、列举 docs')
        self.assertEqual(db_items[0]['exec_view']['rows'][0]['actions'],[0,1])
        self.assertEqual(db_items[1]['native_actions'][0]['additions'],2)
        self.assertEqual(db_items[1]['native_actions'][1]['deletions'],2)
        self.assertEqual(db_items[1]['native_actions'][2]['old_path'],'old')
        for items in (rollout,db_items):
            preview=json.dumps(server.page_payload(items,{}))
            self.assertNotIn('one shared output',preview)
            self.assertNotIn('actual file contents',preview)

    def test_native_interaction_preserves_missing_input_and_known_duration(self):
        from contextlib import nullcontext
        item=dict(type='CommandExecution',source='unifiedExecInteraction',processId='demo',
                  duration=dict(secs=2,nanos=2000000),status='in_progress')
        entry=server.parse_rollout(nullcontext([record('event_msg',dict(type='item_completed',item=item))]))[0][0]
        result=entry['native_results'][0]
        self.assertEqual(entry['exec_view']['label'],'后台终端交互')
        self.assertEqual(result['duration_ms'],2002)
        self.assertEqual(result['process_id'],'demo')
        self.assertNotIn('interaction_input',result)


if __name__=='__main__':unittest.main()

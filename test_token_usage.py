import json
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
from token_usage import scan, report, CACHE


def count(input_tokens, cached=0, output=0, reasoning=0):
    return dict(input_tokens=input_tokens, cached_input_tokens=cached,
                output_tokens=output, reasoning_output_tokens=reasoning)

def event(payload, timestamp='2026-11-04T16:30:00Z', kind='event_msg'):
    return json.dumps(dict(type=kind, timestamp=timestamp, payload=payload))+'\n'

def usage(total, last, timestamp='2026-11-04T16:30:00Z'):
    return event(dict(type='token_count',info=dict(total_token_usage=total,last_token_usage=last)),timestamp)


class RecordedUsage(unittest.TestCase):
    def test_progress_reports_scoped_unique_sessions_and_can_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            rows=[dict(id='a',cwd='/project',rollout_path=str(home/'missing'))]*2
            rows.append(dict(id='b',cwd='/other',rollout_path=str(home/'other')))
            updates=[]
            report(rows,home,dict(scope=['session'],scope_id=['a']),on_progress=lambda done,total:updates.append((done,total)))
            self.assertEqual(updates,[(0,1),(1,1)])
            updates=[]
            report([],home,{},on_progress=lambda done,total:updates.append((done,total)))
            self.assertEqual(updates,[(0,0)])
            def cancel(done,total):raise BrokenPipeError('client disconnected')
            with patch('token_usage.events_for') as scan_file:
                with self.assertRaises(BrokenPipeError):
                    report(rows,home,{},on_progress=cancel)
                scan_file.assert_not_called()

    def test_turn_models_preserve_recorded_changes_without_thread_model_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            recorded, missing = home/'recorded.jsonl', home/'missing.jsonl'
            recorded.write_text(event({'turn_id':'t1','model':'example-a'},kind='turn_context')+
                usage(count(100),count(100))+
                event({'turn_id':'t1','model':'example-b'},kind='turn_context')+
                usage(count(120),count(20)))
            missing.write_text(event({'turn_id':'t2'},kind='turn_context')+usage(count(50),count(50)))
            result = report([dict(id=key,title=key,cwd='/project',model='thread-default',rollout_path=str(path))
                for key,path in [('recorded',recorded),('missing',missing)]],home,dict(dimension=['turn']))
            models = {group['thread_id']:group['models'] for group in result['groups']}
            self.assertEqual(models,dict(recorded=['example-a','example-b'],missing=[]))
            self.assertEqual({m['model']: m['total'] for m in result['models']},
                             {'example-a': 100, 'example-b': 20, None: 50})
            selected = report([dict(id='s', rollout_path=str(recorded))], home,
                              dict(dimension=['turn'], selected=['s/t1'], day=['2026-11-04']))
            self.assertEqual(selected['models'], [])

    def test_purchase_amount_is_consistent_across_scopes_and_time_buckets(self):
        import pricing
        CACHE.clear()
        with tempfile.TemporaryDirectory() as directory, patch.object(pricing, 'LOCAL', Path(directory)/'pricing'):
            home = Path(directory)
            path = home/'purchase.jsonl'
            path.write_text(event({'type':'thread_settings_applied','thread_settings':{'service_tier':'default'}})+
                event({'turn_id':'t1','cwd':'/project','model':'gpt-example'},kind='turn_context')+
                usage(count(600000,200000,50000,10000),count(600000,200000,50000,10000)))
            pricing.save_json(pricing.LOCAL/'credits.json', {'data': {'models': {
                'gpt-example': {'input':50,'cached':2.5,'output':250}}}})
            rule = dict(currency='USD',amount='8',credits='80')
            pricing.configure(dict(basis='purchase',credit_rule=rule))
            rows = [dict(id='s',title='Test',cwd='/project',rollout_path=str(path))]
            for scope, identifier, dimension in [('all','','directory'),('directory','/project','session'),('session','s','turn')]:
                result = report(rows,home,dict(scope=[scope],scope_id=[identifier],dimension=[dimension]))
                self.assertEqual(result['pricing']['unit'], 'USD')
                self.assertEqual(result['cost']['credits'], 33)
                self.assertEqual(result['cost']['value'], 3.3)
                self.assertEqual(result['models'][0]['cost'], result['cost'])
                self.assertEqual(sum(g['cost']['value'] for g in result['groups']), 3.3)
                self.assertEqual(sum(b['cost']['value'] for b in result['buckets']), 3.3)
                self.assertEqual(sum(b['cost']['value'] for b in result['daily']), 3.3)
            hour = report(rows,home,dict(scope=['session'],scope_id=['s'],dimension=['turn'],selected=['s/t1'],day=['2026-11-05']))
            self.assertEqual(sum(b['cost']['value'] for b in hour['buckets']), 3.3)
            pricing.configure(dict(credit_rule=None))
            missing = report(rows,home,{})
            self.assertIsNone(missing['cost']['value'])
            self.assertEqual(missing['cost']['credits'], 33)
            self.assertIsNone(missing['daily'][0]['cost']['value'])
            self.assertEqual(missing['daily'][0]['cost']['credits'],33)

    def test_turn_labels_use_requests_with_reply_fallback_and_stable_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'labels.jsonl'
            request = '# Files mentioned by the user:\n## photo.png: /tmp/photo.png\n## My request:\n把 **入口** 放到左下角\n<image name="photo">image data</image>'
            reply = '<send_user_message_question_reply>'+json.dumps([{'question':'选择哪个？','answer':'采用第二个方案'}])+'</send_user_message_question_reply>'
            path.write_text(
                event({'type':'task_started','turn_id':'no-usage'})+
                event({'type':'task_started','turn_id':'a'})+
                event({'type':'message','role':'user','content':[{'type':'input_text','text':'# AGENTS.md instructions\ninternal rules'}]},kind='response_item')+
                event({'turn_id':'a'},kind='turn_context')+
                event({'type':'message','role':'user','content':[{'type':'input_text','text':request}]},kind='response_item')+
                event({'turn_id':'a'},kind='turn_context')+
                usage(count(100),count(100))+
                event({'type':'task_started','turn_id':'b'})+
                event({'type':'user_message','message':reply})+
                usage(count(120),count(20))+
                event({'type':'task_started','turn_id':'c'})+
                usage(count(130),count(10))+
                event({'type':'message','role':'assistant','phase':'final_answer','content':[{'type':'output_text','text':'已完成布局调整'}]},kind='response_item'))
            events = scan(path)
            self.assertEqual([e['turn_number'] for e in events],[2,3,4])
            self.assertEqual(events[0]['summary'],'把 入口 放到左下角')
            self.assertEqual(events[1]['summary'],'采用第二个方案')
            self.assertEqual(events[2]['summary'],'已完成布局调整')
            self.assertEqual([e['summary_source'] for e in events],['request','request','reply'])
            result = report([dict(id='s',title='Chat',cwd='/project',rollout_path=str(path))],Path(directory),{'dimension':['turn']})
            self.assertEqual([g['summary'] for g in result['groups']],[e['summary'] for e in events])
            self.assertEqual(result['total'],130)

    def test_scopes_limit_totals_costs_groups_and_scans(self):
        CACHE.clear()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            a, b = home/'a.jsonl', home/'b.jsonl'
            a.write_text(event({'turn_id':'t1','cwd':'/project'},kind='turn_context')+
                         usage(count(100),count(100))+
                         event({'turn_id':'t2','cwd':'/other'},kind='turn_context')+
                         usage(count(130),count(30)))
            b.write_text(event({'turn_id':'t3','cwd':'/project'},kind='turn_context')+
                         usage(count(50),count(50)))
            rows = [dict(id='a',title='A',cwd='/project',rollout_path=str(a)),
                    dict(id='b',title='B',cwd='/project',rollout_path=str(b)),
                    dict(id='missing',cwd='/outside',rollout_path=str(home/'missing'))]
            with patch('token_usage.Estimator') as estimator:
                estimator.return_value.calculate.side_effect = lambda e: (Decimal(sum(e['tokens'].values())), None)
                estimator.return_value.metadata.return_value = {}
                from token_usage import events_for
                with patch('token_usage.events_for', wraps=events_for) as scanned:
                    session=report(rows,home,dict(scope=['session'],scope_id=['a'],dimension=['turn']))
                    self.assertEqual(scanned.call_count,1)
                project=report(rows,home,dict(scope=['directory'],scope_id=['/project'],dimension=['session']))
                other=report(rows,home,dict(scope=['directory'],scope_id=['/other'],dimension=['session']))
                all_data=report(rows,home,dict(scope=['all'],dimension=['directory']))
                for result,total in ((session,130),(project,150),(other,30),(all_data,180)):
                    self.assertEqual(result['total'],total)
                    self.assertEqual(result['all_total'],total)
                    self.assertEqual(result['cost']['value'],total)
                    self.assertEqual(sum(g['total'] for g in result['groups']),total)
                    self.assertEqual(sum(b['total'] for b in result['buckets']),total)
                self.assertEqual({g['id'] for g in session['groups']},{'a/t1','a/t2'})
                self.assertEqual({g['id'] for g in project['groups']},{'a','b'})
                self.assertEqual(other['groups'][0]['id'],'a')
                self.assertEqual(project['missing_sessions'],0)
                absent=report(rows,home,dict(scope=['session'],scope_id=['unknown']))
                self.assertEqual(absent['total'],0)
                self.assertEqual(absent['groups'],[])
                hour=report(rows,home,dict(scope=['directory'],scope_id=['/other'],day=['2026-11-05']))
                self.assertEqual(hour['total'],30)
                self.assertEqual(len(hour['buckets']),24)

    def test_dedup_and_inherited_cumulative_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'rollout.jsonl'
            first=count(1000,400,100,20)
            second=count(1100,460,130,30)
            path.write_text(event({'type':'thread_settings_applied','thread_settings':{'service_tier':'default'}})+event({'turn_id':'t1','cwd':'/a'},kind='turn_context')+
                            usage(first,count(100,40,10,2))*2+
                            event({'type':'thread_settings_applied','thread_settings':{'service_tier':'priority'}})+event({'turn_id':'t2','cwd':'/b'},kind='turn_context')+
                            usage(second,count(100,60,30,10))+
                            usage(first,count(100,40,10,2)))
            events=scan(path)
            self.assertEqual(len(events),2)
            self.assertEqual(sum(events[0]['tokens'].values()),110)
            self.assertEqual(events[1]['tokens'],dict(input=40,cached=60,cache_write=0,output=20,reasoning=10))
            self.assertEqual(events[1]['cwd'],'/b')
            self.assertEqual([e['tier'] for e in events],['standard','fast'])

    def test_dimensions_day_hour_zero_fill_and_missing_records(self):
        CACHE.clear()
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            path=home/'rollout.jsonl'
            path.write_text(event({'turn_id':'t1','cwd':'/a'},kind='turn_context')+
                            usage(count(100,30,10,2),count(100,30,10,2))+
                            event({'turn_id':'t2','cwd':'/b'},kind='turn_context')+
                            usage(count(200,80,30,7),count(100,50,20,5),'2026-11-05T02:00:00Z'))
            rows=[dict(id='s1',title='Test',cwd='/old',rollout_path=str(path)),
                  dict(id='missing',title='Missing',cwd='/a',rollout_path=str(home/'missing'))]
            for dimension in ('turn','session','directory'):
                data=report(rows,home,dict(dimension=[dimension],timezone=['Asia/Singapore']))
                self.assertEqual(data['total'],230)
                self.assertEqual(sum(group['total'] for group in data['groups']),230)
                self.assertEqual(sum(bucket['total'] for bucket in data['buckets']),230)
                self.assertEqual(data['missing_sessions'],1)
            hour=report(rows,home,dict(dimension=['turn'],selected=['s1/t1'],day=['2026-11-05']))
            self.assertEqual(len(hour['buckets']),24)
            self.assertEqual(hour['buckets'][0]['total'],110)
            self.assertEqual(hour['total'],110)
            self.assertEqual([(b['label'],b['total']) for b in hour['daily']], [('2026-11-05',110)])
            unselected=report(rows,home,dict(day=['2026-11-04']))
            self.assertEqual(unselected['total'],0)
            self.assertEqual([(b['label'],b['total']) for b in unselected['daily']],[('2026-11-05',230)])
            utc=report(rows,home,dict(timezone=['UTC']))
            self.assertEqual([(b['label'],b['total']) for b in utc['daily']],[('2026-11-04',110),('2026-11-05',120)])
            absent=report(rows,home,dict(day=['2026-11-04']))
            self.assertEqual(absent['total'],0)
            # A changed file invalidates the cached usage.
            with path.open('a') as stream:
                stream.write(usage(count(210,80,30,7),count(10),'2026-11-05T03:00:00Z'))
            self.assertEqual(report(rows,home,{})['total'],240)

if __name__=='__main__':
    unittest.main()

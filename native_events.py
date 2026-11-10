"""Normalize rollout and app-server tool events for the history UI."""

EVENT_TYPES = {
    'websearch': 'web', 'sleep': 'sleep', 'imagegeneration': 'generation',
    'dynamictoolcall': 'dynamic', 'subagentactivity': 'agent_activity',
    'collabagenttoolcall': 'agent_call',
}
EXTENSIONS = {'web.search': 'web', 'clock.sleep': 'sleep', 'image_gen.generation': 'generation'}
ALIASES = {
    'contentItems': 'content_items', 'duration_ms': 'durationMs', 'revised_prompt': 'revisedPrompt',
    'saved_path': 'savedPath', 'transparent_background': 'transparentBackground',
    'agent_thread_id': 'agentThreadId', 'agent_path': 'agentPath',
    'sender_thread_id': 'senderThreadId', 'receiver_thread_ids': 'receiverThreadIds',
    'receiver_agents': 'receiverAgents', 'agents_states': 'agentsStates', 'reasoning_effort': 'reasoningEffort',
}
COLLAB_ACTIONS = {
    'spawnAgent': 'spawn_agent', 'spawn_agent': 'spawn_agent', 'wait': 'wait_agent',
    'sendInput': 'send_message', 'send_input': 'send_message', 'sendMessage': 'send_message', 'send_message': 'send_message',
    'followupTask': 'followup_task', 'followup_task': 'followup_task',
    'interruptAgent': 'interrupt_agent', 'interrupt_agent': 'interrupt_agent',
    'listAgents': 'list_agents', 'list_agents': 'list_agents',
}
AGENT_LABEL_KEYS = {
    'started': 'tools.native.agent.started',
    'interacted': 'tools.native.agent.interacted',
    'completed': 'tools.native.agent.completed',
    'interrupted': 'tools.native.agent.interrupted',
}
TOOL_LABEL_KEYS = {
    'spawn_agent': 'tools.native.spawn',
    'wait_agent': 'tools.native.wait',
    'send_message': 'tools.native.send',
    'followup_task': 'tools.native.followup',
    'interrupt_agent': 'tools.native.interrupt',
    'list_agents': 'tools.native.list',
}


def family(event):
    typ=str(event.get('type', '')).lower()
    return EXTENSIONS.get(str(event.get('kind'))) if typ=='extension' else EVENT_TYPES.get(typ)


def normalize(event):
    """Keep original records separately; use the same field names in the detail renderer."""
    kind=family(event)
    if not kind:
        return event
    item=dict(event,native_family=kind)
    for old,new in ALIASES.items():
        if old in item and new not in item:
            item[new]=item.pop(old)
    if kind=='dynamic' and 'durationMs' not in item:
        duration=item.get('duration')
        if isinstance(duration,dict):
            seconds,nanos=duration.get('secs'),duration.get('nanos')
            if isinstance(seconds,int) and isinstance(nanos,int) and seconds>=0 and 0<=nanos<1_000_000_000:
                item['durationMs']=seconds*1000+nanos//1_000_000
    if kind=='web' and isinstance(item.get('action'),dict):
        action=dict(item['action'])
        action['type']={'open_page':'openPage','find_in_page':'findInPage'}.get(action.get('type'),action.get('type'))
        item['action']=action
    return item


def dynamic_name(event):
    namespace=event.get('namespace') or ''
    tool=event.get('tool') or ''
    return namespace+'__'+tool if namespace else tool


def dynamic_identity(name,event):
    tool=dynamic_name(event)
    return name in (tool, 'mcp__'+tool, (event.get('namespace') or '')+'.'+(event.get('tool') or ''))


def same_direct_kind(tool,event):
    """Additional identity check when an event ID equals a direct call ID."""
    kind=family(event)
    if kind=='web':
        return tool in ('web.run','web__run','mcp__codex_apps__search_service_web_run')
    if kind=='generation':
        return tool in ('image_gen__imagegen','image_gen.imagegen')
    if kind=='dynamic':
        return dynamic_identity(tool,event)
    if kind=='sleep':
        return tool in ('clock.sleep','clock__sleep')
    if kind=='agent_call':
        return tool in (COLLAB_ACTIONS.get(event.get('tool')), 'collaboration.'+str(COLLAB_ACTIONS.get(event.get('tool'))))
    if kind=='agent_activity':
        return isinstance(tool,str) and tool.removeprefix('collaboration.') in ('spawn_agent','followup_task','send_message','interrupt_agent','wait_agent')
    return False


def image_payload(url):
    if not isinstance(url,str) or not url.startswith('data:image/'):
        return None
    header,separator,data=url.partition(',')
    return data if separator and header.endswith(';base64') and data else None


def has_returned_image(owner,event):
    result=event.get('result')
    if not isinstance(result,str) or not result:
        return False
    payload=image_payload(result) or result
    return any(isinstance(block,dict) and block.get('type')=='image'
               and image_payload(block.get('image_url'))==payload for block in owner.get('output_blocks',[]))


def bind_returned_images(items):
    """Nested images can complete during wait. Bind only an exact matching media block
    from one of the requests that was pending when the native event was recorded."""
    kept=[]
    for item in items:
        candidates=item.pop('_image_candidates',[])
        if candidates:
            event=item['tool_events'][0]
            matches=[owner for owner in candidates if has_returned_image(owner,event)]
            if len(matches)==1:
                owner=matches[0]
                related={key:value for key,value in event.items() if key!='result'}
                related['matched_return_image']=True
                owner.setdefault('tool_events',[]).append(related)
                owner['_raw_lines']=sorted(owner['_raw_lines']+item['_raw_lines'])
                continue
        kept.append(item)
    for item in kept:
        for event in item.get('tool_events',[]):
            if family(event)=='generation' and has_returned_image(item,event):
                event.pop('result')
                event['matched_return_image']=True
    return kept

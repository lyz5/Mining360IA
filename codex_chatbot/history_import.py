"""Idempotent import; original conversations and artifacts are never deleted."""
from django.db import transaction
from reports.models import AIConversation
from .models import CodexConversation, CodexMessage


@transaction.atomic
def import_history(*, user=None):
    source=AIConversation.objects.all().prefetch_related('messages','artifacts')
    if user is not None:source=source.filter(user=user)
    counts={'conversations':0,'messages':0}
    for old in source.iterator(chunk_size=100):
        target,created=CodexConversation.objects.get_or_create(legacy_conversation_id=old.pk,defaults={
            'owner_id':old.user_id,'title':old.title[:180],
            'status':{'active':'ACTIVE','archived':'ARCHIVED','deleted':'DELETED'}[old.status]})
        if target.owner_id != old.user_id:raise ValueError('History owner mismatch')
        counts['conversations']+=int(created)
        artifacts=list(old.artifacts.all())
        if created:
            target.legacy_context = {
                'title': old.title,
                'conversation': old.conversation_context_json,
                'performance': old.performance_context_json,
                'knowledge': old.knowledge_context_json,
                'analysis': old.active_analysis_json,
                'artifacts': [{'id':str(a.id),'title':a.title,'type':a.artifact_type,'payload':a.payload_json}
                              for a in artifacts],
            }
            target.save(update_fields=['legacy_context'])
        for message in old.messages.all():
            copied,new=CodexMessage.objects.get_or_create(legacy_message_id=message.pk,defaults={
                'conversation':target,'role':message.role.upper() if message.role!='tool' else 'SYSTEM',
                'content':message.content,'answer_status':'IMPORTED_HISTORY',
                'legacy_payload':{'role':message.role,'status':message.status,'metadata':message.metadata_json,
                    'artifacts':[{'id':str(a.id),'title':a.title,'type':a.artifact_type,'payload':a.payload_json}
                                 for a in artifacts if a.message_id==message.pk]}})
            if copied.conversation_id!=target.pk:raise ValueError('History conversation mismatch')
            if new:CodexMessage.objects.filter(pk=copied.pk).update(created_at=message.created_at)
            counts['messages']+=int(new)
        if created:CodexConversation.objects.filter(pk=target.pk).update(created_at=old.created_at,updated_at=old.updated_at)
    return counts

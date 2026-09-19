"""Compatibility entry points; retired generation never invokes the legacy LLM."""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from urllib.parse import urlencode
from django.views.decorators.http import require_GET
from .access import codex_chatbot_access_required
from .models import CodexConversation


@require_GET
@codex_chatbot_access_required
def home(request, conversation_id=None):
    if conversation_id:
        conversation = get_object_or_404(CodexConversation.objects.exclude(status="DELETED"),
                                        legacy_conversation_id=conversation_id, owner=request.user)
        return redirect("codex_chatbot:conversation", conversation_id=conversation.pk)
    destination = reverse("codex_chatbot:home")
    draft = request.GET.get("draft", "")[:3000]
    if draft:
        destination += "?" + urlencode({"draft": draft})
    return redirect(destination)


@codex_chatbot_access_required
def retired(request, **kwargs):
    return JsonResponse({"ok": False, "error": "Use M360 Chatbot for this conversation.",
                         "chatbot_url": "/codex-chatbot/", "submit_url": "/codex-chatbot/api/runs/"}, status=410)

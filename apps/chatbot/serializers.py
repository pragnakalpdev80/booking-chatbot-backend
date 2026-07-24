# chatbot/serializers.py
from rest_framework import serializers

from .models import ConversationSession, Message


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "content", "timestamp"]
        read_only_fields = fields


class ConversationSessionSerializer(serializers.ModelSerializer):
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = ConversationSession
        fields = [
            "id",
            "session_key",
            "user_email",
            "provider",
            "created_at",
            "updated_at",
            "message_count",
        ]
        read_only_fields = fields

    def get_message_count(self, obj) -> int:
        return obj.messages.count()


class SendMessageSerializer(serializers.Serializer):
    """Input for POST /api/chat/message/"""

    session_key = serializers.UUIDField()
    message = serializers.CharField(max_length=4000)

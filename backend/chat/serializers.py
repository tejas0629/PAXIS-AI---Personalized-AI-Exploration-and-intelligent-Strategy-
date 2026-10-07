from rest_framework import serializers


class ChatMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=(('user', 'User'), ('assistant', 'Assistant')))
    message = serializers.CharField(trim_whitespace=True, allow_blank=False, max_length=4000)


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(trim_whitespace=True, allow_blank=False, max_length=4000)
    conversation_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    messages = ChatMessageSerializer(many=True, required=False, default=list)

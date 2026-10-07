from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import ChatRequestSerializer
from .services import (
    GeminiConfigurationError,
    GeminiResponseError,
    GroqConfigurationError,
    GroqResponseError,
    generate_learning_response,
)


class ChatAPIView(APIView):
    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_message = serializer.validated_data['message']
        conversation_id = serializer.validated_data.get('conversation_id') or None
        previous_messages = serializer.validated_data.get('messages', [])
        previous_messages = [
            {'role': item['role'], 'message': item['message']}
            for item in previous_messages
        ]

        try:
            ai_response, roadmap = generate_learning_response(user_message, previous_messages)
        except GeminiConfigurationError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except GeminiResponseError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except (GroqConfigurationError, GroqResponseError):
            return Response(
                {'error': 'AI service is temporarily unavailable. Please try again shortly.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception:
            return Response(
                {'error': 'AI service is temporarily unavailable. Please try again shortly.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        payload = {'response': ai_response, 'conversation_id': conversation_id}
        if roadmap:
            payload['roadmap'] = roadmap
        return Response(payload)

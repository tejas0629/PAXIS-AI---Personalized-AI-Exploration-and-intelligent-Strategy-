from django.urls import path
from .views import ChatAPIView, ChatStreamAPIView

urlpatterns = [
	path('chat/', ChatAPIView.as_view(), name='chat'),
	path('chat/stream/', ChatStreamAPIView.as_view(), name='chat-stream'),
]

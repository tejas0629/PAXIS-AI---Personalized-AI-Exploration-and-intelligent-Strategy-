const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export async function sendChatMessage(message, conversationId = null, messages = []) {
  const response = await fetch(`${API_BASE_URL}/api/chat/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      messages,
    }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || 'Unable to reach the learning assistant.');
  }
  return data;
}

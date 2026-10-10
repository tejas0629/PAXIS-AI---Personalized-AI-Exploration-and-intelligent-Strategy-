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

export async function streamChatMessage(message, conversationId, messages, onEvent, signal) {
  const response = await fetch(`${API_BASE_URL}/api/chat/stream/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      messages,
    }),
    signal,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || 'Unable to reach the learning assistant.');
  }
  if (!response.body) throw new Error('Streaming is not supported by this connection.');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let completedEvent = null;
  let streamEnded = false;

  const dispatch = (block) => {
    const data = block
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n');
    if (!data) return;
    let event;
    try {
      event = JSON.parse(data);
    } catch {
      throw new Error('The assistant sent an invalid streaming event.');
    }
    if (event.type === 'error') throw new Error(event.message || 'The assistant could not complete the response.');
    if (event.type === 'done') completedEvent = event;
    onEvent(event);
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n');
      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        dispatch(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');
      }
      if (done) {
        streamEnded = true;
        break;
      }
    }
    if (buffer.trim()) dispatch(buffer);
  } finally {
    if (!streamEnded) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }

  if (!completedEvent) throw new Error('The response stream ended before completion.');
  return completedEvent;
}

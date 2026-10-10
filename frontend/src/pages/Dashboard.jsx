import { useEffect, useRef, useState } from 'react';
import Header from '../components/Header.jsx';
import ChatPanel from '../components/ChatPanel.jsx';
import RoadmapPanel from '../components/RoadmapPanel.jsx';
import { streamChatMessage } from '../services/chatApi.js';
import {
  clearConversation,
  loadConversations,
  saveConversation,
  saveMessage,
  saveRoadmap,
} from '../services/indexedDB.js';

const welcome = {
  id: 'welcome',
  role: 'assistant',
  content: 'Hi! Share your career or skill goal, timeline, current level, and daily study time. I’ll create a practical learning roadmap for you.',
};

function createId() {
  return crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function toClientMessage(message) {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
  };
}

export default function Dashboard() {
  const [messages, setMessages] = useState([]);
  const [roadmap, setRoadmap] = useState(null);
  const [conversationId, setConversationId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const activeRequestRef = useRef(null);

  useEffect(() => {
    let active = true;
    loadConversations()
      .then((savedConversations) => {
        if (!active) return;
        const restored = savedConversations[0];
        if (restored) {
          setConversationId(restored.id);
          setMessages(restored.messages.map(toClientMessage));
          setRoadmap(restored.roadmap);
        } else {
          setMessages([welcome]);
        }
      })
      .catch(() => {
        if (active) setError('Saved chat could not be restored. The current session will continue without local persistence.');
      });
    return () => {
      active = false;
    };
  }, []);

  const handleSend = async (content) => {
    const activeConversationId = conversationId || createId();
    const now = new Date().toISOString();
    const assistantMessageId = createId();
    const userMessage = {
      id: createId(),
      conversationId: activeConversationId,
      role: 'user',
      content,
      createdAt: now,
    };
    const assistantMessage = {
      id: assistantMessageId,
      conversationId: activeConversationId,
      role: 'assistant',
      content: '',
      status: 'Understanding your learning goal...',
      streaming: true,
      createdAt: now,
    };
    const nextMessages = [...messages, userMessage];
    const request = { controller: new AbortController(), assistantMessageId };
    activeRequestRef.current = request;
    let accumulatedResponse = '';
    setMessages([...nextMessages, assistantMessage]);
    setConversationId(activeConversationId);
    setLoading(true);
    setError('');

    try {
      await Promise.all([
        saveConversation({ id: activeConversationId, updatedAt: now }),
        saveMessage(userMessage),
      ]);
      const data = await streamChatMessage(
        content,
        activeConversationId,
        nextMessages.map(({ role, content: messageContent }) => ({ role, message: messageContent })),
        (event) => {
          if (event.type === 'chunk') {
            accumulatedResponse += event.text;
            setMessages((current) => current.map((message) => (
              message.id === assistantMessageId
                ? { ...message, content: accumulatedResponse }
                : message
            )));
          } else if (event.type === 'progress') {
            setMessages((current) => current.map((message) => (
              message.id === assistantMessageId
                ? { ...message, status: event.message }
                : message
            )));
          } else if (event.type === 'roadmap') {
            setRoadmap(event.roadmap);
            saveRoadmap(activeConversationId, event.roadmap).catch(() => {});
          }
        },
        request.controller.signal,
      );
      const completedMessage = {
        ...assistantMessage,
        content: accumulatedResponse,
        status: '',
        streaming: false,
        createdAt: new Date().toISOString(),
      };
      setMessages((current) => current.map((message) => (
        message.id === assistantMessageId ? completedMessage : message
      )));
      await Promise.all([
        saveMessage(completedMessage),
        saveConversation({ id: activeConversationId, updatedAt: new Date().toISOString() }),
        ...(data.roadmap ? [saveRoadmap(activeConversationId, data.roadmap)] : []),
      ]);
      setConversationId(data.conversation_id || activeConversationId);
      if (data.roadmap) setRoadmap(data.roadmap);
    } catch (err) {
      if (activeRequestRef.current !== request) return;
      const cancelled = request.controller.signal.aborted;
      if (accumulatedResponse) {
        const partialMessage = {
          ...assistantMessage,
          content: accumulatedResponse,
          status: cancelled ? 'Generation stopped.' : '',
          streaming: false,
          createdAt: new Date().toISOString(),
        };
        setMessages((current) => current.map((message) => (
          message.id === assistantMessageId ? partialMessage : message
        )));
        await saveMessage(partialMessage).catch(() => {});
      } else {
        setMessages((current) => current.filter((message) => message.id !== assistantMessageId));
      }
      if (!cancelled) setError(err.message || 'Unable to reach the learning assistant.');
    } finally {
      if (activeRequestRef.current === request) {
        activeRequestRef.current = null;
        setLoading(false);
      }
    }
  };

  const handleCancel = () => activeRequestRef.current?.controller.abort();

  const handleClear = async () => {
    const activeRequest = activeRequestRef.current;
    activeRequestRef.current = null;
    activeRequest?.controller.abort();
    setLoading(false);
    if (conversationId) {
      try {
        await clearConversation(conversationId);
      } catch {
        setError('The saved conversation could not be cleared completely.');
      }
    }
    setMessages([welcome]);
    setRoadmap(null);
    setConversationId(null);
    setError('');
  };

  const activeProgress = loading
    ? [...messages].reverse().find((message) => message.streaming)?.status || ''
    : '';

  return (
    <>
      <Header />
      <main className="dashboard">
        <ChatPanel
          messages={messages}
          onSend={handleSend}
          onClear={handleClear}
          onCancel={handleCancel}
          loading={loading}
          error={error}
        />
        <RoadmapPanel roadmap={roadmap} progress={activeProgress} />
      </main>
    </>
  );
}

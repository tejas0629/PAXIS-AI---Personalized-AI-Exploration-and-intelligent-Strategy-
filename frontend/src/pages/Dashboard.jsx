import { useEffect, useState } from 'react';
import Header from '../components/Header.jsx';
import ChatPanel from '../components/ChatPanel.jsx';
import RoadmapPanel from '../components/RoadmapPanel.jsx';
import { sendChatMessage } from '../services/chatApi.js';
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
    const userMessage = {
      id: createId(),
      conversationId: activeConversationId,
      role: 'user',
      content,
      createdAt: now,
    };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setConversationId(activeConversationId);
    setLoading(true);
    setError('');

    try {
      await Promise.all([
        saveConversation({ id: activeConversationId, updatedAt: now }),
        saveMessage(userMessage),
      ]);
      const data = await sendChatMessage(
        content,
        activeConversationId,
        nextMessages.map(({ role, content: messageContent }) => ({ role, message: messageContent })),
      );
      const assistantMessage = {
        id: createId(),
        conversationId: activeConversationId,
        role: 'assistant',
        content: data.response,
        createdAt: new Date().toISOString(),
      };
      setMessages((current) => [...current, assistantMessage]);
      await Promise.all([
        saveMessage(assistantMessage),
        saveConversation({ id: activeConversationId, updatedAt: new Date().toISOString() }),
        ...(data.roadmap ? [saveRoadmap(activeConversationId, data.roadmap)] : []),
      ]);
      setConversationId(data.conversation_id || activeConversationId);
      if (data.roadmap) setRoadmap(data.roadmap);
    } catch (err) {
      setError(err.message || 'Unable to reach the learning assistant.');
    } finally {
      setLoading(false);
    }
  };

  const handleClear = async () => {
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

  return (
    <>
      <Header />
      <main className="dashboard">
        <ChatPanel
          messages={messages}
          onSend={handleSend}
          onClear={handleClear}
          loading={loading}
          error={error}
        />
        <RoadmapPanel roadmap={roadmap} />
      </main>
    </>
  );
}

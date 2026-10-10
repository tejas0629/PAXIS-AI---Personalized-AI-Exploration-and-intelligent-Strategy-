import { useEffect, useMemo, useRef, useState } from 'react';
import Header from '../components/Header.jsx';
import ChatPanel from '../components/ChatPanel.jsx';
import ConversationSidebar from '../components/ConversationSidebar.jsx';
import RoadmapPanel from '../components/RoadmapPanel.jsx';
import { streamChatMessage } from '../services/chatApi.js';
import {
  clearConversation,
  deleteConversation,
  loadConversations,
  saveConversation,
  saveMessage,
  saveRoadmap,
  saveRoadmapProgress,
} from '../services/indexedDB.js';

function createId() {
  return crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createConversation() {
  const now = new Date().toISOString();
  return {
    id: createId(),
    title: 'New chat',
    manualTitle: false,
    createdAt: now,
    updatedAt: now,
    messages: [],
    roadmap: null,
    completedItems: [],
  };
}

function titleFromMessage(content) {
  const normalized = content.replace(/\s+/g, ' ').trim();
  if (!normalized) return 'New chat';
  return normalized.length > 42 ? `${normalized.slice(0, 39).trimEnd()}...` : normalized;
}

function applyConversationUpdate(setConversations, conversationId, update) {
  setConversations((current) => current.map((conversation) => (
    conversation.id === conversationId ? update(conversation) : conversation
  )));
}

function getSavedTheme() {
  try {
    return localStorage.getItem('paxis-theme') === 'dark' ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

function getSavedConversationId() {
  try {
    return localStorage.getItem('paxis-active-conversation');
  } catch {
    return null;
  }
}

export default function Dashboard() {
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(getSavedConversationId);
  const [requestStates, setRequestStates] = useState({});
  const [error, setError] = useState('');
  const [theme, setTheme] = useState(getSavedTheme);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [mobileView, setMobileView] = useState('chat');
  const [confirmAction, setConfirmAction] = useState(null);
  const activeRequestsRef = useRef(new Map());

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#101013' : '#f5f8fc');
    try {
      localStorage.setItem('paxis-theme', theme);
    } catch {
      setError('Theme preference could not be saved on this device.');
    }
  }, [theme]);

  useEffect(() => {
    try {
      if (activeId) localStorage.setItem('paxis-active-conversation', activeId);
      else localStorage.removeItem('paxis-active-conversation');
    } catch {
      setError('The active chat preference could not be saved.');
    }
  }, [activeId]);

  useEffect(() => {
    let mounted = true;
    loadConversations()
      .then(async (saved) => {
        if (!mounted) return;
        if (saved.length) {
          setConversations(saved);
          setActiveId(saved.some((conversation) => conversation.id === activeId) ? activeId : saved[0].id);
          return;
        }
        const initial = createConversation();
        await saveConversation(initial);
        if (mounted) {
          setConversations([initial]);
          setActiveId(initial.id);
        }
      })
      .catch(async () => {
        if (!mounted) return;
        setError('Chat history could not be opened. This session can continue without local history.');
        const initial = createConversation();
        setConversations([initial]);
        setActiveId(initial.id);
      });
    return () => {
      mounted = false;
      for (const request of activeRequestsRef.current.values()) request.controller.abort();
      activeRequestsRef.current.clear();
    };
  }, []);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) || null,
    [activeId, conversations],
  );
  const messages = activeConversation?.messages || [];
  const roadmap = activeConversation?.roadmap || null;
  const activeRequest = activeId ? activeRequestsRef.current.get(activeId) : null;
  const loading = Boolean(activeId && requestStates[activeId]);
  const streamingMessage = [...messages].reverse().find((message) => message.streaming);
  const activeProgress = streamingMessage?.progress || '';
  const searching = streamingMessage?.searching || null;

  const handleNewChat = async () => {
    const conversation = createConversation();
    setConversations((current) => [conversation, ...current]);
    setActiveId(conversation.id);
    setMobileView('chat');
    setMobileSidebarOpen(false);
    setError('');
    try {
      await saveConversation(conversation);
    } catch {
      setError('This new chat could not be saved locally.');
    }
  };

  const handleSelectConversation = (conversationId) => {
    setActiveId(conversationId);
    setError('');
    setMobileView('chat');
  };

  const handleRename = async (conversationId, title) => {
    const conversation = conversations.find((item) => item.id === conversationId);
    if (!conversation) return;
    const updated = { ...conversation, title, manualTitle: true, updatedAt: new Date().toISOString() };
    setConversations((current) => current.map((item) => item.id === conversationId ? updated : item));
    await saveConversation({
      id: conversationId,
      title: updated.title,
      manualTitle: true,
      createdAt: updated.createdAt,
      updatedAt: updated.updatedAt,
    }).catch(() => setError('The chat title could not be saved.'));
  };

  const performDelete = async (conversationId) => {
    const request = activeRequestsRef.current.get(conversationId);
    activeRequestsRef.current.delete(conversationId);
    request?.controller.abort();
    setRequestStates((current) => ({ ...current, [conversationId]: false }));
    try {
      await deleteConversation(conversationId);
      const remaining = conversations.filter((item) => item.id !== conversationId);
      if (remaining.length) {
        setConversations(remaining);
        if (activeId === conversationId) setActiveId(remaining[0].id);
      } else {
        const fresh = createConversation();
        setConversations([fresh]);
        setActiveId(fresh.id);
        await saveConversation(fresh);
      }
    } catch {
      setError('This chat could not be deleted from local storage.');
    }
  };

  const handleDelete = (conversationId) => {
    const conversation = conversations.find((item) => item.id === conversationId);
    if (!conversation) return;
    setConfirmAction({
      kind: 'delete',
      conversationId,
      title: `Delete “${conversation.title}”?`,
      message: 'This removes the chat, its messages, roadmap, and saved learning progress from this device.',
      actionLabel: 'Delete chat',
    });
  };

  const performClear = async (conversationId) => {
    const targetConversation = conversations.find((conversation) => conversation.id === conversationId);
    if (!targetConversation) return;
    const request = activeRequestsRef.current.get(conversationId);
    activeRequestsRef.current.delete(conversationId);
    request?.controller.abort();
    setRequestStates((current) => ({ ...current, [conversationId]: false }));
    try {
      await clearConversation(conversationId);
      applyConversationUpdate(setConversations, conversationId, (conversation) => ({
        ...conversation,
        messages: [],
        roadmap: null,
        completedItems: [],
        title: conversation.manualTitle ? conversation.title : 'New chat',
        updatedAt: new Date().toISOString(),
      }));
      await saveConversation({
        id: conversationId,
        createdAt: targetConversation.createdAt,
        title: targetConversation.manualTitle ? targetConversation.title : 'New chat',
        manualTitle: targetConversation.manualTitle || false,
        updatedAt: new Date().toISOString(),
      });
      setError('');
    } catch {
      setError('This chat could not be cleared completely.');
    }
  };

  const handleClear = () => {
    if (!activeConversation || !messages.length) return;
    setConfirmAction({
      kind: 'clear',
      conversationId: activeId,
      title: 'Clear this chat?',
      message: 'Messages, the roadmap, and learning progress will be removed. The chat will remain in history.',
      actionLabel: 'Clear chat',
    });
  };

  const confirmPendingAction = () => {
    const action = confirmAction;
    setConfirmAction(null);
    if (action?.kind === 'delete') performDelete(action.conversationId);
    if (action?.kind === 'clear') performClear(action.conversationId);
  };

  const handleSend = async (content) => {
    if (!activeConversation || activeRequestsRef.current.has(activeId)) return;
    const conversationId = activeId;
    const conversationAtStart = conversations.find((item) => item.id === conversationId);
    if (!conversationAtStart) return;
    const now = new Date().toISOString();
    const request = { controller: new AbortController(), assistantMessageId: createId() };
    const userMessage = {
      id: createId(),
      conversationId,
      role: 'user',
      content,
      createdAt: now,
    };
    const assistantMessage = {
      id: request.assistantMessageId,
      conversationId,
      role: 'assistant',
      content: '',
      progress: 'Planning your learning path…',
      streaming: true,
      createdAt: now,
    };
    const firstMessage = conversationAtStart.messages.length === 0;
    const updatedConversation = {
      ...conversationAtStart,
      error: '',
      title: firstMessage && !conversationAtStart.manualTitle ? titleFromMessage(content) : conversationAtStart.title,
      createdAt: conversationAtStart.createdAt || now,
      updatedAt: now,
      messages: [...conversationAtStart.messages, userMessage, assistantMessage],
    };
    activeRequestsRef.current.set(conversationId, request);
    setRequestStates((current) => ({ ...current, [conversationId]: true }));
    setConversations((current) => [updatedConversation, ...current.filter((item) => item.id !== conversationId)]);
    setError('');

    try {
      await Promise.all([
        saveConversation({
          id: conversationId,
          title: updatedConversation.title,
          manualTitle: updatedConversation.manualTitle,
          createdAt: updatedConversation.createdAt,
          updatedAt: now,
        }),
        saveMessage(userMessage),
      ]);
      const response = await streamChatMessage(
        content,
        conversationId,
        conversationAtStart.messages.map(({ role, content: message }) => ({ role, message })),
        async (event) => {
          if (activeRequestsRef.current.get(conversationId) !== request) return;
          if (event.type === 'chunk') {
            request.accumulatedResponse = (request.accumulatedResponse || '') + event.text;
            applyConversationUpdate(setConversations, conversationId, (conversation) => ({
              ...conversation,
              messages: conversation.messages.map((message) => (
                message.id === request.assistantMessageId
                  ? { ...message, content: request.accumulatedResponse }
                  : message
              )),
            }));
          } else if (event.type === 'progress') {
            applyConversationUpdate(setConversations, conversationId, (conversation) => ({
              ...conversation,
              messages: conversation.messages.map((message) => (
                message.id === request.assistantMessageId
                  ? { ...message, progress: event.message, searching: event.topic ? { topic: event.topic, kind: event.search_kind || 'resources' } : null }
                  : message
              )),
            }));
          } else if (event.type === 'roadmap') {
            applyConversationUpdate(setConversations, conversationId, (conversation) => ({ ...conversation, roadmap: event.roadmap }));
            await saveRoadmap(conversationId, event.roadmap);
          }
        },
        request.controller.signal,
      );
      if (activeRequestsRef.current.get(conversationId) !== request) return;
      const completedMessage = {
        ...assistantMessage,
        content: request.accumulatedResponse || '',
        progress: '',
        searching: null,
        streaming: false,
        createdAt: new Date().toISOString(),
      };
      applyConversationUpdate(setConversations, conversationId, (conversation) => ({
        ...conversation,
        error: '',
        updatedAt: completedMessage.createdAt,
        messages: conversation.messages.map((message) => message.id === request.assistantMessageId ? completedMessage : message),
        roadmap: response.roadmap || conversation.roadmap,
      }));
      await Promise.all([
        saveMessage(completedMessage),
        saveConversation({
          id: conversationId,
          title: updatedConversation.title,
          manualTitle: updatedConversation.manualTitle,
          createdAt: updatedConversation.createdAt,
          updatedAt: completedMessage.createdAt,
        }),
        ...(response.roadmap ? [saveRoadmap(conversationId, response.roadmap)] : []),
      ]);
    } catch (err) {
      if (activeRequestsRef.current.get(conversationId) !== request) return;
      const cancelled = request.controller.signal.aborted;
      const accumulatedResponse = request.accumulatedResponse || '';
      if (accumulatedResponse) {
        const partialMessage = {
          ...assistantMessage,
          content: accumulatedResponse,
          progress: cancelled ? 'Generation stopped.' : '',
          searching: null,
          streaming: false,
          createdAt: new Date().toISOString(),
        };
        applyConversationUpdate(setConversations, conversationId, (conversation) => ({
          ...conversation,
          error: cancelled ? '' : (err.message || 'Unable to reach the learning assistant.'),
          updatedAt: partialMessage.createdAt,
          messages: conversation.messages.map((message) => message.id === request.assistantMessageId ? partialMessage : message),
        }));
        await Promise.all([
          saveMessage(partialMessage).catch(() => {}),
          saveConversation({ ...updatedConversation, updatedAt: partialMessage.createdAt, messages: undefined }).catch(() => {}),
        ]);
      } else {
        applyConversationUpdate(setConversations, conversationId, (conversation) => ({
          ...conversation,
          error: cancelled ? '' : (err.message || 'Unable to reach the learning assistant.'),
          messages: conversation.messages.filter((message) => message.id !== request.assistantMessageId),
        }));
      }
    } finally {
      if (activeRequestsRef.current.get(conversationId) === request) {
        activeRequestsRef.current.delete(conversationId);
        setRequestStates((current) => ({ ...current, [conversationId]: false }));
      }
    }
  };

  const handleToggleProgress = async (itemId) => {
    if (!activeConversation) return;
    const completedItems = activeConversation.completedItems || [];
    const nextItems = completedItems.includes(itemId)
      ? completedItems.filter((item) => item !== itemId)
      : [...completedItems, itemId];
    applyConversationUpdate(setConversations, activeId, (conversation) => ({ ...conversation, completedItems: nextItems }));
    await saveRoadmapProgress(activeId, nextItems).catch(() => setError('Learning progress could not be saved.'));
  };

  const toggleTheme = () => setTheme((current) => current === 'light' ? 'dark' : 'light');

  return (
    <div className={`appShell theme-${theme}`}>
      <Header
        theme={theme}
        onToggleTheme={toggleTheme}
        onOpenSidebar={() => setMobileSidebarOpen(true)}
      />
      <div className={`workspace ${sidebarCollapsed ? 'sidebarCollapsed' : ''}`}>
        <ConversationSidebar
          conversations={conversations}
          activeId={activeId}
          collapsed={sidebarCollapsed}
          mobileOpen={mobileSidebarOpen}
          onNewChat={handleNewChat}
          onSelect={handleSelectConversation}
          onRename={handleRename}
          onDelete={handleDelete}
          onCloseMobile={() => setMobileSidebarOpen(false)}
          onToggleCollapsed={() => setSidebarCollapsed((current) => !current)}
        />
        <main className="workspaceMain">
          <div className="mobileTabs" role="tablist" aria-label="Conversation panels">
            <button type="button" role="tab" aria-selected={mobileView === 'chat'} className={mobileView === 'chat' ? 'selected' : ''} onClick={() => setMobileView('chat')}>Chat</button>
            <button type="button" role="tab" aria-selected={mobileView === 'roadmap'} className={mobileView === 'roadmap' ? 'selected' : ''} onClick={() => setMobileView('roadmap')}>Roadmap</button>
          </div>
          <section className={`chatPane ${mobileView === 'chat' ? 'mobileVisible' : ''}`}>
            <ChatPanel
              key={activeId || 'loading'}
              title={activeConversation?.title || 'New chat'}
              messages={messages}
              onSend={handleSend}
              onClear={handleClear}
              onCancel={() => activeRequest?.controller.abort()}
              loading={loading}
              error={error}
            />
          </section>
          <section className={`roadmapPane ${mobileView === 'roadmap' ? 'mobileVisible' : ''}`}>
            <RoadmapPanel
              roadmap={roadmap}
              progress={loading ? activeProgress : ''}
              searching={loading ? searching : null}
              completedItems={activeConversation?.completedItems || []}
              onToggleProgress={handleToggleProgress}
            />
          </section>
        </main>
      </div>
      {confirmAction && (
        <div className="dialogBackdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setConfirmAction(null); }}>
          <section className="confirmDialog" role="alertdialog" aria-modal="true" aria-labelledby="confirmTitle" aria-describedby="confirmMessage">
            <h2 id="confirmTitle">{confirmAction.title}</h2>
            <p id="confirmMessage">{confirmAction.message}</p>
            <div className="dialogActions">
              <button type="button" className="dialogCancel" autoFocus onClick={() => setConfirmAction(null)}>Cancel</button>
              <button type="button" className="dialogConfirm" onClick={confirmPendingAction}>{confirmAction.actionLabel}</button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

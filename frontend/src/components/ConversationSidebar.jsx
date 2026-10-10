import { useState } from 'react';

function formatDate(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const today = new Date();
  return date.toDateString() === today.toDateString()
    ? date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

export default function ConversationSidebar({
  conversations,
  activeId,
  collapsed,
  mobileOpen,
  onNewChat,
  onSelect,
  onRename,
  onDelete,
  onCloseMobile,
  onToggleCollapsed,
}) {
  const [editingId, setEditingId] = useState(null);
  const [draftTitle, setDraftTitle] = useState('');

  const startRename = (conversation) => {
    setEditingId(conversation.id);
    setDraftTitle(conversation.title || 'New chat');
  };

  const finishRename = (event, conversationId) => {
    event.preventDefault();
    const title = draftTitle.trim();
    if (title) onRename(conversationId, title);
    setEditingId(null);
  };

  return (
    <>
      {mobileOpen && <button className="drawerScrim" type="button" aria-label="Close chat history" onClick={onCloseMobile} />}
      <aside className={`conversationSidebar ${collapsed ? 'isCollapsed' : ''} ${mobileOpen ? 'mobileOpen' : ''}`}>
        <div className="sidebarTop">
          <button className="sidebarBrand" type="button" onClick={onToggleCollapsed} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
            <span className="brandMark" aria-hidden="true">P</span>
            {!collapsed && <span>PAXIS-AI</span>}
          </button>
          <button className="iconButton sidebarCollapse" type="button" onClick={onToggleCollapsed} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
            <span aria-hidden="true">{collapsed ? '›' : '‹'}</span>
          </button>
        </div>

        <button className="newChatButton" type="button" onClick={onNewChat} title="New chat" aria-label="New chat">
          <span className="newChatIcon" aria-hidden="true">+</span>
          {!collapsed && <span>New Chat</span>}
        </button>

        {!collapsed && <div className="historyLabel">RECENT CHATS</div>}
        <nav className="conversationList" aria-label="Chat history">
          {conversations.map((conversation) => (
            <div className={`conversationItem ${conversation.id === activeId ? 'isActive' : ''}`} key={conversation.id}>
              {editingId === conversation.id ? (
                <form className="renameForm" onSubmit={(event) => finishRename(event, conversation.id)}>
                  <input
                    aria-label="Conversation title"
                    autoFocus
                    value={draftTitle}
                    onChange={(event) => setDraftTitle(event.target.value)}
                    onKeyDown={(event) => { if (event.key === 'Escape') setEditingId(null); }}
                    maxLength={64}
                  />
                </form>
              ) : (
                <button
                  className="conversationSelect"
                  type="button"
                  onClick={() => { onSelect(conversation.id); onCloseMobile(); }}
                  title={conversation.title}
                  aria-current={conversation.id === activeId ? 'page' : undefined}
                >
                  <span className="conversationGlyph" aria-hidden="true">◷</span>
                  {!collapsed && (
                    <span className="conversationTitleGroup">
                      <span className="conversationTitle">{conversation.title || 'New chat'}</span>
                      <span className="conversationDate">{formatDate(conversation.updatedAt)}</span>
                    </span>
                  )}
                </button>
              )}
              {!collapsed && editingId !== conversation.id && (
                <div className="conversationActions">
                  <button type="button" onClick={() => startRename(conversation)} aria-label={`Rename ${conversation.title}`} title="Rename chat">✎</button>
                  <button type="button" onClick={() => onDelete(conversation.id)} aria-label={`Delete ${conversation.title}`} title="Delete chat">×</button>
                </div>
              )}
            </div>
          ))}
          {!conversations.length && !collapsed && <p className="historyEmpty">Your chats will appear here.</p>}
        </nav>

        {!collapsed && (
          <div className="sidebarFooter">
            <span className="sidebarFooterDot" />
            <span>Private on this device</span>
            <a href="https://github.com/tejas0629/SARP-Smart-AI-roadmap-Provider-" target="_blank" rel="noopener noreferrer">About</a>
          </div>
        )}
      </aside>
    </>
  );
}

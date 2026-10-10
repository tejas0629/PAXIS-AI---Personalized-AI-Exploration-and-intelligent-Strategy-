import { useEffect, useRef, useState } from 'react';

export default function ChatPanel({ messages, onSend, onClear, onCancel, loading, error }) {
  const [text, setText] = useState('');
  const messagesRef = useRef(null);
  const stickToBottomRef = useRef(true);
  useEffect(() => {
    const container = messagesRef.current;
    if (container && stickToBottomRef.current) container.scrollTop = container.scrollHeight;
  }, [messages, loading]);
  const submit = (event) => {
    event.preventDefault();
    if (text.trim() && !loading) {
      onSend(text.trim());
      setText('');
    }
  };
  return (
    <section className="chatCard">
      <div className="panelHeader">
        <div>
          <h2>AI Learning Assistant</h2>
          <p><span className="onlineDot" /> Online</p>
        </div>
        <button className="ghostBtn" onClick={onClear}>🗑️ Clear Chat</button>
      </div>
      <div
        className="messages"
        ref={messagesRef}
        onScroll={(event) => {
          const container = event.currentTarget;
          stickToBottomRef.current = container.scrollHeight - container.scrollTop - container.clientHeight < 80;
        }}
      >
        {messages.map((m) => (
          <div className={`messageRow ${m.role}`} key={m.id}>
            <div className="bubbleAvatar">{m.role === 'assistant' ? '🤖' : '👤'}</div>
            <div className="bubble">
              <pre>{m.content}</pre>
              {m.streaming && !m.content && (
                <span className="typingIndicator" role="status" aria-label="Assistant is responding">
                  <i /><i /><i />
                </span>
              )}
              {m.streaming && m.status && <div className="streamStatus">{m.status}</div>}
              {!m.streaming && m.status && <div className="streamStatus stoppedStatus">{m.status}</div>}
            </div>
          </div>
        ))}
      </div>
      {error && <div className="errorBox" role="alert">{error}</div>}
      <form className="composer" onSubmit={submit}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type your message..." />
        {loading ? (
          <button type="button" className="stopButton" onClick={onCancel} aria-label="Stop generating">
            <span aria-hidden="true">■</span> Stop
          </button>
        ) : (
          <button type="submit" disabled={!text.trim()}><span aria-hidden="true">➤</span> Send</button>
        )}
      </form>
    </section>
  );
}

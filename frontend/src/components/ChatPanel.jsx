import { useEffect, useRef, useState } from 'react';

export default function ChatPanel({ title, messages, onSend, onClear, onCancel, loading, error }) {
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
          <h2>{title || 'New chat'}</h2>
          <p><span className="onlineDot" /> PAXIS assistant</p>
        </div>
        <button className="ghostBtn" type="button" onClick={onClear} disabled={!messages.length}>Clear chat</button>
      </div>
      <div
        className="messages"
        ref={messagesRef}
        onScroll={(event) => {
          const container = event.currentTarget;
          stickToBottomRef.current = container.scrollHeight - container.scrollTop - container.clientHeight < 80;
        }}
      >
        {!messages.length && (
          <div className="chatEmptyState">
            <span className="emptyWordmark">PAXIS</span>
            <h3>What would you like to learn?</h3>
            <p>Share a skill, goal, or timeline to start building your learning path.</p>
          </div>
        )}
        {messages.map((m) => (
          <div className={`messageRow ${m.role}`} key={m.id}>
            <div className={`bubbleAvatar ${m.role === 'assistant' ? 'assistantAvatar' : ''}`} aria-hidden="true">{m.role === 'assistant' ? 'P' : 'You'}</div>
            <div className="bubble">
              <pre>{m.content}</pre>
              {m.streaming && !m.content && (
                <span className="typingIndicator" role="status" aria-label="Assistant is responding">
                  <i /><i /><i />
                </span>
              )}
              {m.streaming && m.progress && <div className="streamStatus">{m.progress}</div>}
              {!m.streaming && m.progress && <div className="streamStatus stoppedStatus">{m.progress}</div>}
            </div>
          </div>
        ))}
      </div>
      {error && <div className="errorBox" role="alert">{error}</div>}
      <form className="composer" onSubmit={submit}>
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              submit(event);
            }
          }}
          placeholder="Ask PAXIS about a learning goal..."
          rows={1}
          aria-label="Message PAXIS-AI"
          disabled={loading}
        />
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

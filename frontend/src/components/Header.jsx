export default function Header({ theme, onToggleTheme, onOpenSidebar }) {
  return (
    <header className="appHeader">
      <button className="iconButton mobileMenuButton" type="button" onClick={onOpenSidebar} aria-label="Open chat history">
        <span className="menuGlyph" aria-hidden="true">☰</span>
      </button>
      <div className="headerCopy">
        <h1>Welcome to PAXIS-AI</h1>
        <p>Personalized AI Exploration and Intelligent Strategy</p>
      </div>
      <button
        className="iconButton themeToggle"
        type="button"
        onClick={onToggleTheme}
        aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
        title={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
      >
        <span aria-hidden="true">{theme === 'light' ? '◐' : '☼'}</span>
        <span className="themeLabel">{theme === 'light' ? 'Dark' : 'Light'} theme</span>
      </button>
    </header>
  );
}

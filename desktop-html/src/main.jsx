import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './app/App.jsx';
// 顺序要紧：legacy 先进层，tailwind 的 utilities 后进层 → utilities 才能覆盖旧样式
import './legacy.css';
import './tailwind.css';
import './theme.css';

class ErrorBoundary extends React.Component {
  state = { error: null };
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (this.state.error) return <div className="fatal"><img src="/brand.png" width="44" /><h2>界面暂时没有加载完成</h2><p>{this.state.error.message}</p><button onClick={() => location.reload()}>重新加载</button></div>;
    return this.props.children;
  }
}
createRoot(document.getElementById('root')).render(<ErrorBoundary><App /></ErrorBoundary>);

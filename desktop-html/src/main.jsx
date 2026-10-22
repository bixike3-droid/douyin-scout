import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './app/App.jsx';
import './styles.css';

class ErrorBoundary extends React.Component {
  state = { error: null };
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (this.state.error) return <div className="fatal"><img src="/brand.png" width="44" /><h2>界面暂时没有加载完成</h2><p>{this.state.error.message}</p><button onClick={() => location.reload()}>重新加载</button></div>;
    return this.props.children;
  }
}
createRoot(document.getElementById('root')).render(<ErrorBoundary><App /></ErrorBoundary>);

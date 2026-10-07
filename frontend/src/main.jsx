import React from 'react';
import { createRoot } from 'react-dom/client';
import { registerSW } from 'virtual:pwa-register';
import App from './App.jsx';
import './styles.css';

registerSW({ immediate: true });

createRoot(document.getElementById('root')).render(<App />);

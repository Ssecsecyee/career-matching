import React from 'react';
import {createRoot} from 'react-dom/client';
import {AppRouter} from './AppRouter.jsx';
import './style.css';

createRoot(document.getElementById('root')).render(<AppRouter/>);

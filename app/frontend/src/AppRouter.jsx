import React, {useEffect,useState} from 'react';
import {Admin} from './Admin.jsx';
import {CareerApp} from './CareerApp.jsx';
import {workspaceRoute} from './workspaceRoute.js';

export function AppRouter(){
 const [hash,setHash]=useState(window.location.hash);
 useEffect(()=>{const change=()=>setHash(window.location.hash);window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change);},[]);
 useEffect(()=>{if(!hash || hash==='#chat'){window.history.replaceState(null,'','#jobs');setHash('#jobs');}},[hash]);
 const route=workspaceRoute(hash);
 return route.mode==='admin'?<Admin/>:<CareerApp key={route.mode} page={route.page} adminChat={route.mode==='admin-chat'}/>;
}

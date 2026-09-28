'use strict';
const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
async function postJSON(url, data) {
  const response = await fetch(url, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRFToken':csrf()}, body:JSON.stringify(data)});
  let result;
  try { result = await response.json(); } catch (_) { throw new Error('Please refresh the page and sign in again if needed.'); }
  if (!response.ok) throw new Error(result.error || 'This action could not be completed.');
  return result;
}
document.querySelector('#menu-toggle')?.addEventListener('click', event => {
  const open = document.querySelector('#sidebar').classList.toggle('is-open');
  event.currentTarget.setAttribute('aria-expanded', String(open));
});
document.querySelectorAll('[data-confirm]').forEach(button => button.addEventListener('click', event => {
  if (!window.confirm(button.dataset.confirm)) event.preventDefault();
}));
document.querySelectorAll('.attachment-picker input').forEach(input => input.addEventListener('change', () => {
  input.parentElement.querySelector('.attachment-count').textContent = input.files.length ? `(${input.files.length} selected)` : '';
}));
document.querySelector('#refresh-conversation')?.addEventListener('click', () => window.location.reload());
const thread = document.querySelector('#conversation-messages');
if (thread) thread.scrollTop = thread.scrollHeight;
if (thread?.dataset.updatesUrl) {
  const indicator=document.querySelector('#conversation-refresh');
  indicator.querySelector('button').addEventListener('click',()=>window.location.reload());
  setInterval(async()=>{
    if (document.hidden) return;
    try {
      const response=await fetch(thread.dataset.updatesUrl);
      if (!response.ok) return;
      const data=await response.json();
      if (data.last_message_id!==Number(thread.dataset.lastId) || data.status!==thread.dataset.status) {
        const editing=[...document.querySelectorAll('textarea')].some(field=>field.value.trim()) || [...document.querySelectorAll('input[type=file]')].some(field=>field.files.length);
        if (!editing && !document.querySelector('form:focus-within')) window.location.reload();
        else indicator.hidden=false;
      }
    } catch (_) {}
  },20000);
}
const planner = document.querySelector('#planner');
if (planner) {
  const conversation = document.querySelector('#assistant-messages');
  const form = document.querySelector('#assistant-form');
  const input = document.querySelector('#chat-input');
  const summary = document.querySelector('#generate-summary');
  const error = document.querySelector('#assistant-error');
  let busy = false;
  function append(message) {
    const element = document.createElement('div');
    element.className = 'chat-message ' + (message.role === 'user' ? 'outgoing' : 'ai');
    const label = document.createElement('div'); label.className = 'message-label';
    label.textContent = message.role === 'user' ? 'You' : 'HelloSama assistant';
    const body = document.createElement('div'); body.className = 'message-body'; body.textContent = message.content;
    element.append(label,body);
    if (message.sources?.length) {
      const sources = document.createElement('div'); sources.className = 'source-links';
      message.sources.forEach(source => {
        try {
          const url = new URL(source.url);
          if (!['http:','https:'].includes(url.protocol)) return;
          const link=document.createElement('a'); link.href=url.href; link.textContent=source.title; link.target='_blank'; link.rel='noopener noreferrer';sources.append(link);
        } catch (_) {}
      });
      element.append(sources);
    }
    conversation.append(element); conversation.scrollTop=conversation.scrollHeight;
  }
  function setBusy(value) {
    busy=value; form.querySelector('button').disabled=value; summary.disabled=value;
    error.textContent=value?'Your assistant is working on it…':'';
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !input.value.trim()) return;
    const message=input.value.trim(); append({role:'user',content:message}); input.value='';setBusy(true);
    try { const result=await postJSON(planner.dataset.aiUrl,{message}); append(result.message); setBusy(false); }
    catch (err) {setBusy(false);error.textContent=err.message;}
  });
  summary.addEventListener('click',async () => {
    if (busy) return;setBusy(true);
    try {
      const result=await postJSON(planner.dataset.aiUrl,{action:'summary'});
      Object.entries(result.summary).forEach(([key,value])=>{
        const field=document.querySelector(`#request-form [name="${key}"]`);
        if (field) field.value=value;
      });
      setBusy(false);error.textContent='Your summary is ready. Review the details, fill any gaps, then submit.';
      document.querySelector('.request-summary').scrollIntoView({behavior:'smooth',block:'start'});
    } catch (err) {setBusy(false);error.textContent=err.message;}
  });
  conversation.scrollTop=conversation.scrollHeight;
}
function pushStatus(text) {document.querySelectorAll('.push-status').forEach(el=>el.textContent=text);}
document.querySelectorAll('.push-enable').forEach(button=>button.addEventListener('click',async()=>{
  try {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) throw new Error('This browser does not support device notifications. On iPhone or iPad, add HelloSama to your Home Screen first.');
    const permission=await Notification.requestPermission();
    if (permission!=='granted') throw new Error('Notifications were not enabled. You can change this in your browser settings.');
    const config=await (await fetch('/api/push/config/')).json();
    if (!config.public_key) throw new Error('Device notifications are not configured yet.');
    await navigator.serviceWorker.register('/service-worker.js');
    const registration=await navigator.serviceWorker.ready;
    const raw=atob(config.public_key.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-config.public_key.length%4)%4));
    const key=Uint8Array.from(raw,c=>c.charCodeAt(0));
    const subscription=await registration.pushManager.getSubscription() || await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
    await postJSON('/api/push/subscribe/',subscription.toJSON());pushStatus('Notifications are enabled on this device.');
  } catch (error) {pushStatus(error.message);}
}));
document.querySelectorAll('.push-disable').forEach(button=>button.addEventListener('click',async()=>{
  try {
    const registration=await navigator.serviceWorker.getRegistration();
    const subscription=await registration?.pushManager.getSubscription();
    if (subscription) {await postJSON('/api/push/unsubscribe/',{endpoint:subscription.endpoint});await subscription.unsubscribe();}
    pushStatus('Notifications are disabled on this device.');
  } catch (error) {pushStatus(error.message);}
}));
if (document.querySelector('[data-unread]')) setInterval(async()=>{
  if (document.hidden) return;
  try {const response=await fetch('/api/notifications/'); if (response.ok) {const data=await response.json();document.querySelectorAll('[data-unread]').forEach(el=>el.textContent=data.unread);}}catch (_){}
},60000);

(() => {
  const root=document.getElementById('account-list');if(!root)return;
  const list=root.querySelector('.user-list'),status=root.querySelector('.users-result'), more=document.getElementById('users-more');
  const search=document.getElementById('users-search'), sort=document.getElementById('users-sort'), filter=document.getElementById('users-status'), size=document.getElementById('users-page-size');
  let page=1,controller,revision=0,total=0;
  function text(tag,value,cls){const el=document.createElement(tag);el.textContent=value;if(cls)el.className=cls;return el;}
  function link(label,url){const el=text('a',label,'admin-button');el.href=url;return el;}
  async function load(reset){
    controller?.abort();controller=new AbortController();const ticket=++revision;
    if(reset)page=1;
    more.disabled=true;status.textContent='Loading accounts…';
    try{
      const response=await fetch(root.dataset.api+'?'+new URLSearchParams({q:search.value,sort:sort.value,status:filter.value,page,per_page:size.value}),{signal:controller.signal,headers:{Accept:'application/json'}});
      if(!response.ok||response.redirected)throw new Error('Sign in again to view accounts.');
      const data=await response.json();if(ticket!==revision)return;if(reset)list.replaceChildren();total=data.pagination.total;
      data.users.forEach(user=>{
        const entry=document.createElement('article');entry.className='admin-glass user-list-entry';
        const title=document.createElement('div');title.append(text('h3',user.username),text('small',`${user.protocol.toUpperCase()} · ${user.current_devices}/${user.max_devices} devices`));
        const quota=document.createElement('div');quota.append(text('b',`${user.traffic_usage} / ${user.traffic_limit||'Unlimited'} GB`));
        const meter=document.createElement('div');meter.className='user-meter';const fill=document.createElement('span');fill.style.width=Math.max(0,Math.min(100,user.traffic_percent))+'%';meter.append(fill);quota.append(meter,text('small',user.days_left_text));
        const nodes=document.createElement('div');user.nodes_list.forEach(node=>{const row=document.createElement('div');const flag=text('span','','flag');flag.dataset.code=node.country;row.append(flag,text('small',node.name));nodes.append(row);});
        const actions=document.createElement('div');actions.append(text('span',user.customer_paused?'Customer paused':user.status,'user-state '+user.status),link('Profile',root.dataset.base+'/users/view/'+user.id));
        entry.append(title,quota,nodes,actions);list.append(entry);
      });
      status.textContent=`${list.children.length} of ${total} accounts`;more.hidden=!data.pagination.has_next;more.disabled=false;
      window.BeenyFlags?.render?.(list);
      document.dispatchEvent(new Event('beeny-flags-refresh'));
    }catch(error){if(error.name!=='AbortError')status.textContent=error.message||'Could not load accounts. Retry.';more.disabled=false;}
  }
  let timer;search.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>load(true),250);});
  [sort,filter,size].forEach(el=>el.addEventListener('change',()=>load(true)));more.addEventListener('click',()=>{page++;load(false);});load(true);
})();

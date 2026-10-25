import { expect,it,vi } from 'vitest';
import { api } from '../src/api';
it('cancels read requests on page exit and avoids starting requests from an unloading page',async()=>{
 const fetcher=vi.fn((_path:unknown,init:any)=>new Promise((_resolve,reject)=>{init.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')));}));
 vi.stubGlobal('fetch',fetcher);
 try{
  const pending=api('/api/user-files').catch(e=>e.name);
  window.dispatchEvent(new Event('pagehide'));
  expect(await pending).toBe('AbortError');
  await expect(api('/api/user-files')).rejects.toThrow('页面正在刷新');
  expect(fetcher).toHaveBeenCalledTimes(1);
  window.dispatchEvent(new Event('pageshow'));
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({healthy:true})}));
  expect(await api('/api/user-files')).toEqual({healthy:true});
 }finally{window.dispatchEvent(new Event('pageshow'));vi.unstubAllGlobals();}
});

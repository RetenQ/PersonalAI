import { beforeEach, it, expect, vi } from 'vitest';
import { render,screen,waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QuickEntry } from '../src/QuickEntry';
import { mutate } from '../src/api';
vi.mock('../src/api',()=>({mutate:vi.fn()}));
beforeEach(()=>vi.resetAllMocks());
it('keeps text after failure and sends one entry without a task',async()=>{
 const user=userEvent.setup();vi.mocked(mutate).mockRejectedValueOnce(new Error('暂时失败')).mockResolvedValue({});
 render(<QuickEntry today="2026-10-25" tasks={[]} saved={async()=>{}}/>);
 await user.type(screen.getByLabelText('快捷记录内容'),'一条进展');await user.click(screen.getByRole('button',{name:'保存这条记录'}));
 expect((await screen.findByRole('alert')).textContent).toContain('暂时失败');expect((screen.getByLabelText('快捷记录内容') as HTMLInputElement).value).toBe('一条进展');
 await user.click(screen.getByRole('button',{name:'保存这条记录'}));await waitFor(()=>expect((screen.getByLabelText('快捷记录内容') as HTMLInputElement).value).toBe(''));
 expect(mutate).toHaveBeenLastCalledWith('/api/quick-record',{text:'一条进展',date:'2026-10-25',task_id:null,result:'',obstacle:''});
});
it('changing next task keeps unfinished text',async()=>{
 const user=userEvent.setup();const tasks:any[]=[{task_id:'one',record:{text:'First'}},{task_id:'two',record:{text:'Second'}}];
 const view=render(<QuickEntry today="2026-10-25" tasks={tasks} saved={async()=>{}} selectedTask="one"/>);
 await user.type(screen.getByLabelText('快捷记录内容'),'草稿');view.rerender(<QuickEntry today="2026-10-25" tasks={tasks} saved={async()=>{}} selectedTask="two"/>);
 expect((screen.getByLabelText('快捷记录内容') as HTMLInputElement).value).toBe('草稿');expect(screen.queryByLabelText('关联任务')).toBeNull();
});

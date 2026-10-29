import { expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SummaryPage } from '../src/SummaryPage';
import { api } from '../src/api';
vi.mock('../src/api',()=>({api:vi.fn()}));
it('shows goal progress without inventing unknown values or task percentages', async()=>{
  vi.mocked(api).mockResolvedValue({goals:[{id:'a',created_at:'2026-10-28',data:{title:'学习'},progress:0},{id:'b',created_at:'2026-10-28',data:{title:'阅读'},progress:null}],tasks:[{task_id:'t',goal_id:'a',progress:50,record:{text:'练习',status:'open',date:'2026-10-28'}}]});
  render(<SummaryPage ready day="2026-10-28" revision={0} record={vi.fn()}/>);
  const zero=await screen.findByRole('progressbar',{name:'学习：目标进度'});
  expect(zero.getAttribute('aria-valuenow')).toBe('0');
  expect(screen.getByRole('progressbar',{name:'阅读：目标进度'}).getAttribute('aria-valuenow')).toBeNull();
  expect(screen.queryByText('50%')).toBeNull();
  expect(screen.queryByRole('textbox')).toBeNull();
});

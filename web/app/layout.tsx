import './style.css';
import type { ReactNode } from 'react';
export const metadata={title:'DFO Homebush · 优惠核对工作台'};
export default function Layout({children}:{children:ReactNode}){
  return <html lang="zh-CN"><body>{children}</body></html>
}

import {expect,test} from '@playwright/test';
test('ASICS production page, real offline API and trace',async({page})=>{
  await page.goto('/compare');
  await expect(page.getByRole('combobox')).toHaveValue('BF26-02');
  await page.getByRole('button',{name:'运行对照'}).click();
  for(const [name,count] of [['固定查询',3],['规则策略',3]] as const){
    const card=page.getByRole('article',{name,exact:true});
    await expect(card.locator('.verdict')).toHaveText('不适用');
    await expect(card.locator('details')).toHaveCount(count);
    await card.locator('summary').first().click();
    await expect(card.getByText('excluding ASICS Factory Outlets',{exact:true})).toBeVisible();
    await expect(card.getByRole('link').first()).toHaveAttribute('href',/^https:\/\/www.asics.com\//);
  }
  await expect(page.getByText('LLM 不可用',{exact:true})).toBeVisible();
  for(const [id,label] of [['BF26-01','适用'],['BF26-03','证据不足']]){
    await page.getByRole('combobox').selectOption(id);
    await page.getByRole('button',{name:'运行对照'}).click();
    await expect(page.locator('.verdict')).toHaveText([label,label]);
  }
});

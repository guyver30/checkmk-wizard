import { newE2EPage } from '@stencil/core/testing';

describe('kfds-select', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-select></kfds-select>');

    const element = await page.find('kfds-select');
    expect(element).toHaveClass('hydrated');
  });
});

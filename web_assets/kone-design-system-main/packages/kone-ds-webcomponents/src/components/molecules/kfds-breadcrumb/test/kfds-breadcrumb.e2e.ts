import { newE2EPage } from '@stencil/core/testing';

describe('kfds-breadcrumb', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-breadcrumb></kfds-breadcrumb>');

    const element = await page.find('kfds-breadcrumb');
    expect(element).toHaveClass('hydrated');
  });
});

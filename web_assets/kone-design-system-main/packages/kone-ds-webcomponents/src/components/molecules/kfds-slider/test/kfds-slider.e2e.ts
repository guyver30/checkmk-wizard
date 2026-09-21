import { newE2EPage } from '@stencil/core/testing';

describe('kfds-slider', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-slider></kfds-slider>');

    const element = await page.find('kfds-slider');
    expect(element).toHaveClass('hydrated');
  });
});

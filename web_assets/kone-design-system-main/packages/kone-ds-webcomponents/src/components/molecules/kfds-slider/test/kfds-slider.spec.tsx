import { newSpecPage } from '@stencil/core/testing';
import { KfdsSlider } from '../kfds-slider';

describe('kfds-slider', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [KfdsSlider],
      html: `<kfds-slider></kfds-slider>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-slider>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-slider>
    `);
  });
});

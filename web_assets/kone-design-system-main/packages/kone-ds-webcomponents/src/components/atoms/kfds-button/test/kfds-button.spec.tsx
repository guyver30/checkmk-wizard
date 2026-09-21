import { newSpecPage } from '@stencil/core/testing';
import { KfdsButton } from '../kfds-button';

describe('kfds-button', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [KfdsButton],
      html: `<kfds-button></kfds-button>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-button>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-button>
    `);
  });
});

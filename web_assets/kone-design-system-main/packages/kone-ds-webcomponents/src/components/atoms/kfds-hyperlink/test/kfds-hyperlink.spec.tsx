import { newSpecPage } from '@stencil/core/testing';
import { KfdsHyperlink } from '../kfds-hyperlink';

describe('kfds-hyperlink', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [KfdsHyperlink],
      html: `<kfds-hyperlink></kfds-hyperlink>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-hyperlink>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-hyperlink>
    `);
  });
});

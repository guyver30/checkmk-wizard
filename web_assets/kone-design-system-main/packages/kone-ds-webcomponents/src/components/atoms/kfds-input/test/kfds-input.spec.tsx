import { newSpecPage } from '@stencil/core/testing';
import { KfdsInput } from '../kfds-input';

describe('kfds-input', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [KfdsInput],
      html: `<kfds-input></kfds-input>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-input>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-input>
    `);
  });
});

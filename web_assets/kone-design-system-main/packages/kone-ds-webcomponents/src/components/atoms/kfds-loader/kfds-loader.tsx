import { Component, Element, Prop, State, Watch, h } from '@stencil/core';

@Component({
  tag: 'kfds-loader',
  styleUrl: 'kfds-loader.scss',
  shadow: true,
})
export class KfdsLoader {
  @Element() host: HTMLKfdsLoaderElement;

  @State() count = 0;
  @Prop() now = 0;
  @Prop() progressBar: 'show' | 'hidden';
  @Prop() progressNum: 'show' | 'hidden';
  @Prop() videoBackground: 'show' | 'hidden';
  @Prop() restartButton: 'show' | 'hidden';
  @Prop() appName: string;
  @Prop() elementId: string;
  @Prop() customClass: string;

  componentDidLoad() {
    this.startLoading();
  }
  componentWillLoad() {
    this.count = !isNaN(this.now) ? this.now : 0;
  }

  @Watch('now')
  watchPropNowHandler(newValue: any) {
    this.count = !isNaN(newValue) ? newValue : 0;
  }

  private startLoading() {
    const logoGroup = this.host.shadowRoot.getElementById('logo');
    if (logoGroup) {
      logoGroup.classList.remove('logoIn');
      logoGroup.classList.add('logoOut');
    }

    window.setTimeout(() => {
      const logoLetters = this.host.shadowRoot.querySelectorAll<HTMLElement>('#k_txt, #o_txt, #n_txt, #e_txt');
      if (logoLetters) {
        logoLetters.forEach(letter => {
          letter.style.opacity = '0';
        });
      }

      const appName = this.host.shadowRoot.getElementById('appName');
      if (appName) {
        appName.classList.remove('fadeOut');
        appName.classList.add('fadeIn');
      }
    }, 1000);

    window.setTimeout(() => {
      const progress = this.host.shadowRoot.getElementById('progress');
      const progressNumElement = this.host.shadowRoot.getElementById('progressNum');
      const kRect = this.host.shadowRoot.getElementById('k_rect');
      const nRect = this.host.shadowRoot.getElementById('n_rect');
      const oRect = this.host.shadowRoot.getElementById('o_rect');
      const eRect = this.host.shadowRoot.getElementById('e_rect');

      progress.classList.remove('fadeOut');
      progress.classList.add('fadeIn');
      progressNumElement.classList.remove('fadeOut');
      progressNumElement.classList.add('fadeIn');

      kRect.classList.add('loadingO');
      nRect.classList.add('loadingO');
      oRect.classList.add('loadingE');
      eRect.classList.add('loadingE');
    }, 1500);

    const interval = setInterval(() => {
      if (this.count >= 99) {
        clearInterval(interval);
        this.loadingDone();
      }
      // this.count += 0.8; // This count should be contolled via @Prop now
      const progress = this.host.shadowRoot.getElementById('progress');
      const progressNumElement = this.host.shadowRoot.getElementById('progressNum');

      if (this.progressBar === 'show') {
        progress.style.visibility = 'visible';
        progress.style.opacity = '1';
        progress.style.width = this.count + '%';
      } else {
        progress.style.visibility = 'hidden';
        progress.style.opacity = '0';
      }

      if (this.progressNum === 'show') {
        progressNumElement.style.visibility = 'visible';
        progressNumElement.style.opacity = '1';
        progressNumElement.innerHTML = Math.round(this.count) + '<sup>%</sup>';
      } else {
        progressNumElement.style.visibility = 'hidden';
        progressNumElement.style.opacity = '0';
      }
    }, 100);

    if (this.videoBackground === 'show') {
      setTimeout(() => {
        const maskRect = this.host.shadowRoot.getElementById('maskRect');
        maskRect.classList.remove('maskZoomIn');
        maskRect.classList.add('maskZoomOut');
      }, 10);
    }
  }

  private loadingDone() {
    if (this.videoBackground === 'show') {
      const maskRect = this.host.shadowRoot.getElementById('maskRect');
      if (maskRect) {
        maskRect.classList.remove('maskZoomOut');
        maskRect.classList.add('maskZoomIn');
      }
    }

    const progress = this.host.shadowRoot.getElementById('progress');
    const progressNum = this.host.shadowRoot.getElementById('progressNum');
    const appName = this.host.shadowRoot.getElementById('appName');
    const kRect = this.host.shadowRoot.getElementById('k_rect');
    const nRect = this.host.shadowRoot.getElementById('n_rect');
    const oRect = this.host.shadowRoot.getElementById('o_rect');
    const eRect = this.host.shadowRoot.getElementById('e_rect');
    const logoLetters = this.host.shadowRoot.querySelectorAll<HTMLElement>('#k_txt, #o_txt, #n_txt, #e_txt');
    const logoGroup = this.host.shadowRoot.getElementById('logo');

    progress.classList.remove('fadeIn');
    progress.classList.add('fadeOut');
    progressNum.classList.remove('fadeIn');
    progressNum.classList.add('fadeOut');

    appName.classList.remove('fadeIn');
    appName.classList.add('fadeOut');
    kRect.classList.remove('loadingO');
    nRect.classList.remove('loadingO');
    oRect.classList.remove('loadingE');
    eRect.classList.remove('loadingE');

    window.setTimeout(() => {
      if (logoLetters) {
        logoLetters.forEach(letter => {
          letter.style.opacity = '1';
        });
      }
    }, 1000);

    window.setTimeout(() => {
      if (logoGroup) {
        logoGroup.classList.remove('logoOut');
        logoGroup.classList.add('logoIn');
      }
    }, 1000);
  }

  restartLoader() {
    this.count = 0;
    const interval = setInterval(() => {
      this.count += 0.8;
      if (this.count >= 99) {
        clearInterval(interval);
      }
    }, 100);
    this.startLoading();
  }
  render() {
    return (
      <div part='loader' class="kfds-loader">
        <div part='container' class="container">
          <video part='video' id="video" autoplay playsinline muted preload="auto" loop poster="https://www.qubic.fi/tmp/bgv.png">
            <source src="https://www.qubic.fi/tmp/bgv.mp4" type="video/mp4" />
          </video>
          <svg part='svg' id="svgMask">
            <mask id="mask">
              <rect x="0" y="0" width="100%" height="100%" fill="white"></rect>
              <rect id="maskRect" x="50%" y="50%" width="100px" height="100px" fill="black" class="maskZoomIn"></rect>
            </mask>
            <rect id="maskBG" x="0" y="0" width="100%" height="100%" fill="white" mask="url(#mask)"></rect>
          </svg>
          <div part='brand' id="brand">
            <svg width="128" height="128" viewBox="0 0 128 128" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">
              <rect class="brand_rect" width="128" height="128" />
              <g id="logo" class="logoIn">
                <rect id="e_rect" x="99" y="39" width="29" height="50" />
                <path id="e_txt" d="M121.5,58.1L111.1,58l-0.1,3.7h8.7l0,4.5h-8.7v3.6h10.4v4.8h-16V53.5h16V58.1z" />
                <rect id="n_rect" x="66" y="39" width="29" height="50" />
                <path id="n_txt" d="M89.9,74.6h-4.7l-8.9-12.4v12.4H71V53.5H76L84.6,65l0.1-11.5l5.2,0V74.6z" />
                <rect id="o_rect" x="33" y="39" width="29" height="50" />
                <path
                  id="o_txt"
                  d="M47.4,53c-6.1,0-11,4.5-11,11.1
		c0,6.6,4.9,11.1,11,11.1c6.1,0,11-4.5,11-11.1C58.4,57.5,53.5,53,47.4,53z M47.4,70.1c-3,0-5.3-2.5-5.3-6.1c0-3.6,2.3-6.1,5.3-6.1
		c3,0,5.3,2.5,5.3,6.1C52.8,67.6,50.5,70.1,47.4,70.1z"
                />
                <rect id="k_rect" y="39" width="29" height="50" />
                <path id="k_txt" d="M18.1,74.6l-7.3-10v10H5.2V53.5l5.5,0l0.1,9.2l7-9.2h6.7l-7.7,10L25,74.6H18.1z" />
              </g>
            </svg>
            <div part='progress' id="progress"></div>
          </div>
          <div part='info' class="info">
            <div part='app-name' id="appName">{this.appName}</div>
            <div part='progress-number' id="progressNum">{this.count}</div>
          </div>
        </div>

        {this.restartButton === 'show' && (
          <button part='restart-button' class="btn" onClick={() => this.restartLoader()}>
            Restart
          </button>
        )}
      </div>
    );
  }
}

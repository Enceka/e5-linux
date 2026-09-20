//色相
let currentHue = 0;
//透明度
let currentOpacity = 1;
// 亮度
let currentValue = 1;
//饱和度
let currentSaturation = 1;
//字体颜色
let currentTextColor = 0;

//主页模糊开关
let homeBlurSwitch = true

//背景overlay开关
let overlaySwitch = true;

// 调色盘
function getColorByPercent(e) {
    const HValue = document.querySelector("#HValue")
    if (HValue) HValue.innerText = (+e.target.value / 100 * 255).toFixed(0)
    const value = e.target.value; // 0 ~ 100
    const h = (value / 100) * 300;
    currentHue = h;
    updateColor();
    //保存进度到localStorage
    localStorage.setItem('colorPer', value);
}

//亮度
function getValueByPercent(e) {
    const LValue = document.querySelector("#LValue")
    if (LValue) LValue.innerText = (+e.target.value / 100 * 255).toFixed(0)
    const value = e.target.value;
    currentValue = value / 100;
    updateColor();
    localStorage.setItem('brightPer', value);
}

// 透明度
function getOpacityByPercent(e) {
    const opacityValue = document.querySelector("#opacityValue")
    if (opacityValue) opacityValue.innerText = (+e.target.value / 100 * 255).toFixed(0)
    const value = e.target.value; // 0 ~ 100
    currentOpacity = value / 100;
    updateColor();
    //保存进度到localStorage
    localStorage.setItem('opacityPer', value);
}

//饱和度
function getSaturationByPercent(e) {
    const SValue = document.querySelector("#SValue")
    if (SValue) SValue.innerText = (+e.target.value / 100 * 255).toFixed(0)
    const value = e.target.value; // 0 ~ 100
    currentSaturation = value / 100;
    updateColor();
    //保存进度到localStorage
    localStorage.setItem('saturationPer', value);
}

//字体颜色
function updateTextColor(e) {
    const fontColorValue = document.querySelector("#fontColorValue")
    if (fontColorValue) fontColorValue.innerText = (+e.target.value / 100 * 255).toFixed(0)
    const value = e.target.value; // 0 ~ 100
    const gray = Math.round((value / 100) * 255);
    const color = `rgb(${gray}, ${gray}, ${gray})`;
    currentTextColor = color;
    updateColor();
    //保存进度到localStorage
    localStorage.setItem('textColorPer', value);
    localStorage.setItem('textColor', color);
}

//主页毛玻璃
function updateBlurSwitch(e) {
    const value = e.target.checked;
    homeBlurSwitch = value
    updateColor()
    //保存进度到localStorage
    localStorage.setItem('blurSwitch', value);
}

//背景遮罩
function updateOverlaySwitch(e) {
    const value = e.target.checked;
    overlaySwitch = value
    updateColor()
    //保存进度到localStorage
    localStorage.setItem('overlaySwitch', value);
}


// 更新颜色 + 透明度
function updateColor() {
    const { r, g, b } = hsvToRgb(currentHue, currentSaturation, currentValue);
    const { h, s, l } = hsvToHsl(currentHue, currentSaturation, currentValue);

    // 基础颜色
    const lighterL = Math.min(l + 20, 100);
    const btnBaseOpacity = Math.min(currentOpacity * 1.2, 1);

    // 正常按钮
    const btnColor = `hsl(${Math.round(h)} ${s.toFixed(1)}% ${lighterL.toFixed(1)}% / ${(btnBaseOpacity * 100).toFixed(2)}%)`;

    // 激活按钮（更亮、更饱和、更实）
    let activeS, activeL;

    if (lighterL > 80) {
        activeS = Math.min(s * 1.8, 100);
        activeL = Math.max(lighterL - 25, 20);
    } else {
        activeS = Math.min(s * 1.6, 100);
        activeL = Math.min(lighterL + 20, 60);
        activeL = Math.max(activeL, 20);
    }

    const btnActiveOpacity = Math.min(btnBaseOpacity + 0.2, 1);
    const btnActiveColor = `hsl(${Math.round(h)} ${activeS.toFixed(1)}% ${activeL.toFixed(1)}% / ${(btnActiveOpacity * 100).toFixed(2)}%)`;

    // 禁用按钮（去饱和、更透明）
    const btnDisabledOpacity = Math.max(btnBaseOpacity - 0.2, 0.1);
    const btnDisabledColor = `hsl(${Math.round(h)} 0% ${lighterL.toFixed(1)}% / ${(btnDisabledOpacity * 100).toFixed(2)}%)`;

    const color = `rgba(${r}, ${g}, ${b}, ${currentOpacity})`;

    // 修改 :root 中的 CSS 变量
    document.documentElement.style.setProperty('--dark-bgi-color', color);
    document.documentElement.style.setProperty('--dark-tag-color', color);
    document.documentElement.style.setProperty('--dark-btn-color', btnColor);
    document.documentElement.style.setProperty('--dark-title-color', btnActiveColor);
    document.documentElement.style.setProperty('--dark-btn-color-active', btnActiveColor);
    document.documentElement.style.setProperty('--dark-btn-disabled-color', btnDisabledColor);
    document.documentElement.style.setProperty('--dark-text-color', currentTextColor);
    document.documentElement.style.setProperty('--blur-rate', homeBlurSwitch ? "4px" : "0");

    //针对Safari -webkit-backdrop-filter 不支持css变量 进行修复
    document.querySelectorAll('.statusCard,thead,tbody,input')?.forEach(el => {
        homeBlurSwitch ? el.classList.add('blur-px') : el.classList.remove('blur-px')
    })

    //去除已存在的style
    const _lastStyle = document.querySelector('#kano_filter_profile_set')
    if(_lastStyle){
        _lastStyle.remove()
    }
    const _style = document.createElement('style')
    _style.id = "kano_filter_profile_set"
    _style.innerHTML = `.deviceList li {backdrop-filter: ${homeBlurSwitch ? "blur(4px) !important" : "none !important"};-webkit-backdrop-filter:  ${homeBlurSwitch ? "blur(4px) !important;" : "none !important;"}) }`
    document.querySelector('.status-container')?.insertAdjacentElement('beforebegin', _style)


    const el = document.querySelector('body');
    el.style.transform = 'translateZ(0)';  // 强制 GPU 图层


    document.querySelector('#BG_OVERLAY').style.backgroundColor = overlaySwitch ? `var(--dark-bgi-color)` : 'transparent';
    //保存到localStorage
    localStorage.setItem('themeColor', currentHue);
}

//读取颜色数据
const initTheme = async (sync = false) => {
    const isCloudSync = document.querySelector("#isCloudSync")

    const isSync = localStorage.getItem("isCloudSync", isCloudSync.checked)
    if (isSync == true || isSync == "true" || sync) {
        // 从云端拉取主题数据
        let result = null
        try {
            result = await (await fetchWithTimeout(KANO_baseURL + "/get_theme", {
                method: 'get'
            })).json()
        } catch (e) {
            result = null
            console.error('云端主题拉取数据失败：', e)
        }

        if (result) {
            Object.keys(result).forEach((key) => {
                localStorage.setItem(key, result[key])
            })
        }
    }
    let color = localStorage.getItem('themeColor');
    let colorPer = localStorage.getItem('colorPer');
    let opacityPer = localStorage.getItem('opacityPer');
    let value = localStorage.getItem('brightPer');
    let saturation = localStorage.getItem('saturationPer');
    let textColor = localStorage.getItem('textColor');
    let textColorPer = localStorage.getItem('textColorPer');
    let blur = localStorage.getItem('blurSwitch');
    let overlay = localStorage.getItem('overlaySwitch');

    if (blur == null || blur == undefined) {
        blur = "true"
        localStorage.setItem('blurSwitch', blur);
    }

    if (overlay == null || overlay == undefined) {
        overlay = "true"
        localStorage.setItem('overlaySwitch', overlay);
    }

    if (color == null || color == undefined) {
        color = 201;
        localStorage.setItem('themeColor', color);
    }
    if (colorPer == null || colorPer == undefined) {
        colorPer = 67;
        localStorage.setItem('colorPer', colorPer);
    }
    if (opacityPer == null || opacityPer == undefined) {
        opacityPer = 21;
        localStorage.setItem('opacityPer', opacityPer);
    }
    if (value == null || value == undefined) {
        value = 21;
        localStorage.setItem('brightPer', value);
    }
    if (saturation == null || saturation == undefined) {
        saturation = 100;
        localStorage.setItem('saturationPer', saturation);
    }
    if (textColor == null || textColor == undefined) {
        textColor = 'rgba(255, 255, 255, 1)';
        localStorage.setItem('textColor', textColor);
    }
    if (textColorPer == null || textColorPer == undefined) {
        textColorPer = 100;
        localStorage.setItem('textColorPer', textColorPer);
    }

    homeBlurSwitch = blur == "true"
    overlaySwitch = overlay == "true"
    currentHue = color;
    currentOpacity = opacityPer / 100;
    currentValue = value / 100;
    currentSaturation = saturation / 100;
    currentTextColor = textColor;
    updateColor();
    try {
        document.querySelector("#colorEl").value = colorPer;
        document.querySelector("#opacityEl").value = opacityPer;
        document.querySelector("#brightEl").value = value;
        document.querySelector("#saturationEl").value = saturation;
        document.querySelector("#textColorEl").value = textColorPer;
        document.querySelector("#blurSwitch").checked = homeBlurSwitch;
        document.querySelector("#overlaySwitch").checked = overlaySwitch;
        document.querySelector("#fontColorValue").innerText = (+textColorPer / 100 * 255).toFixed(0)
        document.querySelector("#HValue").innerText = (+colorPer / 100 * 255).toFixed(0)
        document.querySelector("#SValue").innerText = (+saturation / 100 * 255).toFixed(0)
        document.querySelector("#LValue").innerText = (+value / 100 * 255).toFixed(0)
        document.querySelector("#opacityValue").innerText = (+opacityPer / 100 * 255).toFixed(0)
    } catch (e) {
        createToast(e.message, 'red')
    }
    isCloudSync.checked = isSync == "true"
}
initTheme();

/**
 * VF Logistics - Internationalization (i18n) Module
 * 
 * Simple i18n implementation for the fraud detection dashboard.
 * Supports Vietnamese (vi) and English (en).
 * 
 * Usage:
 *   const i18n = new I18n('vi');
 *   console.log(i18n.t('dashboard.title')); // "VF Logistics | Phát hiện gian lận AI"
 */

const translations = {
  en: {
    dashboard: {
      title: 'VF Logistics | AI Fraud Detection',
      subtitle: 'Autonomous Shipping Fraud Detection with Human-in-the-Loop Governance',
    },
    nav: {
      single: 'Agent Console',
      pipeline: 'Dashboard',
      devops: 'DevOps',
      review: 'Review Queue',
      audit: 'Audit Trail',
      governance: 'Governance',
    },
    status: {
      healthy: 'Healthy',
      suspended: 'Suspended',
      ready: 'Ready',
      loading: 'Loading...',
      error: 'Error',
    },
    cases: {
      ingested: 'Ingested',
      autoCleared: 'Auto-Cleared',
      escalated: 'Escalated',
      heldForReview: 'Held for Review',
      pendingHuman: 'Pending Human',
      deadLetter: 'Dead Letter',
    },
    actions: {
      analyze: 'Analyze',
      upload: 'Upload Document',
      simulate: 'Simulate',
      release: 'Release',
      block: 'Block',
      requestInfo: 'Request Info',
      publish: 'Publish Boundary',
      reset: 'Reset Board',
    },
    risk: {
      low: 'Low Risk',
      medium: 'Medium Risk',
      high: 'High Risk',
      critical: 'Critical',
      floor: 'Deterministic Floor',
      modelScore: 'Model Score',
      effectiveRisk: 'Effective Risk',
      disputed: 'Score Disputed',
    },
    review: {
      title: 'Review Queue',
      noItems: 'No cases awaiting review',
      selectCase: 'Select a case to review',
      reviewerNote: 'Reviewer Note',
      placeholder: 'Enter your review notes...',
    },
    governance: {
      title: 'Delegation Boundary',
      agentState: 'Agent State',
      boundaryVersion: 'Boundary Version',
      publishedBy: 'Published By',
      driftStatus: 'Drift Status',
      autoReleaseRate: 'Auto-Release Rate',
      vetoRate: 'Veto Rate',
      injectionRate: 'Injection Rate',
    },
    errors: {
      networkError: 'Network error. Please check your connection.',
      serverError: 'Server error. Please try again later.',
      unauthorized: 'Unauthorized. Please log in.',
      forbidden: 'Access denied. Insufficient permissions.',
      notFound: 'Resource not found.',
      validationError: 'Validation error. Please check your input.',
      timeout: 'Request timed out. Please try again.',
      unknown: 'An unexpected error occurred.',
    },
    time: {
      justNow: 'just now',
      minutesAgo: '{n} minute(s) ago',
      hoursAgo: '{n} hour(s) ago',
      daysAgo: '{n} day(s) ago',
    },
  },
  vi: {
    dashboard: {
      title: 'VF Logistics | Phát hiện gian lận AI',
      subtitle: 'Phát hiện gian lận vận chuyển tự động với giám sát con người',
    },
    nav: {
      single: 'Bảng điều khiển Agent',
      pipeline: 'Bảng điều khiển',
      devops: 'Vận hành',
      review: 'Hàng chờ duyệt',
      audit: 'Nhật ký kiểm toán',
      governance: 'Quản trị',
    },
    status: {
      healthy: 'Hoạt động tốt',
      suspended: 'Tạm ngừng',
      ready: 'Sẵn sàng',
      loading: 'Đang tải...',
      error: 'Lỗi',
    },
    cases: {
      ingested: 'Đã nhận',
      autoCleared: 'Tự động thông qua',
      escalated: 'Đã báo cáo',
      heldForReview: 'Chờ duyệt',
      pendingHuman: 'Chờ xử lý',
      deadLetter: 'Lỗi nghiêm trọng',
    },
    actions: {
      analyze: 'Phân tích',
      upload: 'Tải tài liệu',
      simulate: 'Mô phỏng',
      release: 'Thông qua',
      block: 'Chặn',
      requestInfo: 'Yêu cầu thêm thông tin',
      publish: 'Công bố ranh giới',
      reset: 'Đặt lại bảng',
    },
    risk: {
      low: 'Rủi ro thấp',
      medium: 'Rủi ro trung bình',
      high: 'Rủi ro cao',
      critical: 'Nghiêm trọng',
      floor: 'Ngưỡng xác định',
      modelScore: 'Điểm mô hình',
      effectiveRisk: 'Rủi ro hiệu dụng',
      disputed: 'Điểm có tranh cãi',
    },
    review: {
      title: 'Hàng chờ duyệt',
      noItems: 'Không có trường hợp nào chờ duyệt',
      selectCase: 'Chọn một trường hợp để duyệt',
      reviewerNote: 'Ghi chú người duyệt',
      placeholder: 'Nhập ghi chú của bạn...',
    },
    governance: {
      title: 'Ranh giới ủy quyền',
      agentState: 'Trạng thái Agent',
      boundaryVersion: 'Phiên bản ranh giới',
      publishedBy: 'Công bố bởi',
      driftStatus: 'Trạng thái lệch',
      autoReleaseRate: 'Tỷ lệ tự động thông qua',
      vetoRate: 'Tỷ lệ phủ quyết',
      injectionRate: 'Tỷ lệ tiêm nhiễm',
    },
    errors: {
      networkError: 'Lỗi mạng. Vui lòng kiểm tra kết nối.',
      serverError: 'Lỗi máy chủ. Vui lòng thử lại sau.',
      unauthorized: 'Chưa xác thực. Vui lòng đăng nhập.',
      forbidden: 'Truy cập bị từ chối. Không đủ quyền.',
      notFound: 'Không tìm thấy tài nguyên.',
      validationError: 'Lỗi xác thực. Vui lòng kiểm tra dữ liệu nhập.',
      timeout: 'Yêu cầu hết thời gian. Vui lòng thử lại.',
      unknown: 'Đã xảy ra lỗi không mong đợi.',
    },
    time: {
      justNow: 'vừa xong',
      minutesAgo: '{n} phút trước',
      hoursAgo: '{n} giờ trước',
      daysAgo: '{n} ngày trước',
    },
  },
};

class I18n {
  constructor(locale = 'en') {
    this.locale = locale;
    this.fallbackLocale = 'en';
  }

  setLocale(locale) {
    if (translations[locale]) {
      this.locale = locale;
      this.updatePageLanguage();
      return true;
    }
    return false;
  }

  getLocale() {
    return this.locale;
  }

  t(key, params = {}) {
    const keys = key.split('.');
    let value = translations[this.locale];
    
    for (const k of keys) {
      if (value && typeof value === 'object' && k in value) {
        value = value[k];
      } else {
        // Fallback to English
        value = translations[this.fallbackLocale];
        for (const fk of keys) {
          if (value && typeof value === 'object' && fk in value) {
            value = value[fk];
          } else {
            return key; // Return key if not found
          }
        }
        break;
      }
    }

    // Replace parameters
    if (typeof value === 'string') {
      for (const [param, val] of Object.entries(params)) {
        value = value.replace(`{${param}}`, val);
      }
    }

    return value;
  }

  // Update all elements with data-i18n attribute
  updatePageLanguage() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      el.textContent = this.t(key);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const key = el.getAttribute('data-i18n-placeholder');
      el.placeholder = this.t(key);
    });
    document.documentElement.lang = this.locale;
  }

  // Relative time formatting
  relativeTime(date) {
    const now = new Date();
    const diff = now - new Date(date);
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return this.t('time.justNow');
    if (minutes < 60) return this.t('time.minutesAgo', { n: minutes });
    if (hours < 24) return this.t('time.hoursAgo', { n: hours });
    return this.t('time.daysAgo', { n: days });
  }
}

// Error handler with i18n support
class ErrorHandler {
  constructor(i18n) {
    this.i18n = i18n;
  }

  getErrorMessage(error, response) {
    if (!response) {
      return this.i18n.t('errors.networkError');
    }

    switch (response.status) {
      case 401:
        return this.i18n.t('errors.unauthorized');
      case 403:
        return this.i18n.t('errors.forbidden');
      case 404:
        return this.i18n.t('errors.notFound');
      case 422:
        return this.i18n.t('errors.validationError');
      case 500:
      case 502:
      case 503:
        return this.i18n.t('errors.serverError');
      case 504:
        return this.i18n.t('errors.timeout');
      default:
        return error?.message || this.i18n.t('errors.unknown');
    }
  }

  showError(error, response) {
    const message = this.getErrorMessage(error, response);
    console.error('Error:', message, error);
    
    // Create toast notification
    const toast = document.createElement('div');
    toast.className = 'error-toast';
    toast.textContent = message;
    toast.style.cssText = `
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: #ea4335;
      color: white;
      padding: 12px 24px;
      border-radius: 8px;
      font-size: 14px;
      z-index: 9999;
      animation: slideIn 0.3s ease-out;
    `;
    document.body.appendChild(toast);
    
    setTimeout(() => {
      toast.style.animation = 'slideOut 0.3s ease-in';
      setTimeout(() => toast.remove(), 300);
    }, 5000);
  }
}

// API client with error handling
class ApiClient {
  constructor(baseUrl = '', errorHandler) {
    this.baseUrl = baseUrl;
    this.errorHandler = errorHandler;
  }

  async request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const defaultOptions = {
      headers: {
        'Content-Type': 'application/json',
      },
    };

    try {
      const response = await fetch(url, { ...defaultOptions, ...options });
      
      if (!response.ok) {
        const error = new Error(`HTTP ${response.status}`);
        this.errorHandler?.showError(error, response);
        throw error;
      }

      return await response.json();
    } catch (error) {
      if (error.name === 'TypeError') {
        // Network error
        this.errorHandler?.showError(error, null);
      }
      throw error;
    }
  }

  get(endpoint) {
    return this.request(endpoint);
  }

  post(endpoint, data) {
    return this.request(endpoint, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }
}

// Export for use in main app
if (typeof window !== 'undefined') {
  window.I18n = I18n;
  window.ErrorHandler = ErrorHandler;
  window.ApiClient = ApiClient;
  window.translations = translations;
}

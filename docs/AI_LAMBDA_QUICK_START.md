# AI Lambda Quick Start Guide

## 🚀 Deploy Your First AI Function in 5 Minutes

This guide shows you how to deploy AI/ML serverless functions with zero infrastructure management.

## Prerequisites

- Access to the Local AI Homelab repository
- Basic knowledge of Python or JavaScript

## Quick Deploy Example

### 1. Create Your AI Function

Create a new directory in `/functions/`:

```bash
mkdir functions/my-ai-function
cd functions/my-ai-function
```

### 2. Write Your Function Code

**`main.py`**
```python
import json
import uuid
from datetime import datetime
import pandas as pd
import numpy as np

def main():
    """AI Lambda function - no infrastructure needed!"""
    from flask import request
    request_id = str(uuid.uuid4())
    
    # Get operation from query params
    operation = request.args.get('operation', 'hello')
    
    if operation == 'hello':
        return {
            'status': 200,
            'body': json.dumps({
                'message': 'Hello from AI Lambda!',
                'request_id': request_id,
                'timestamp': datetime.now().isoformat(),
                'libraries': {
                    'pandas': pd.__version__,
                    'numpy': np.__version__
                }
            }),
            'headers': {'Content-Type': 'application/json'}
        }
    
    elif operation == 'analyze':
        # Demo AI analysis
        data = np.random.normal(100, 15, 50)
        df = pd.DataFrame({'values': data})
        
        analysis = {
            'mean': float(df['values'].mean()),
            'std': float(df['values'].std()),
            'trend': float(np.polyfit(range(len(data)), data, 1)[0])
        }
        
        return {
            'status': 200,
            'body': json.dumps({
                'request_id': request_id,
                'analysis': analysis,
                'data_points': len(data)
            }),
            'headers': {'Content-Type': 'application/json'}
        }
```

### 3. Add Dependencies

**`requirements.txt`**
```txt
pandas==2.1.4
numpy==1.24.3
requests==2.31.0

# Uncomment for AI/ML libraries:
# openai==1.3.0
# scikit-learn==1.3.2
# prophet==1.1.4
```

### 4. Deploy (GitOps Magic ✨)

```bash
git add functions/my-ai-function/
git commit -m "Add my first AI lambda function"
git push origin main
```

### 5. Test Your Function

Wait 60 seconds for deployment, then:

```bash
# Test basic functionality
curl https://functions.example.com/my-ai-function?operation=hello

# Test AI analysis
curl https://functions.example.com/my-ai-function?operation=analyze
```

## That's It! 🎉

Your AI function is now:
- ✅ **Live on the internet** at `https://functions.example.com/my-ai-function`
- ✅ **Auto-scaling** from 0 to N instances based on demand
- ✅ **SSL encrypted** with automatic certificate management
- ✅ **Dependency managed** with automatic pip install
- ✅ **Monitored and logged** with enterprise-grade observability

## Advanced Examples

### OpenAI Integration Function

```python
def main():
    from flask import request
    import openai  # Add to requirements.txt
    
    # Your OpenAI logic here
    # Automatic scaling handles load
    # No infrastructure management needed
```

### ML Model Inference Function

```python
def main():
    import joblib  # or torch, tensorflow
    from flask import request
    
    # Load your pre-trained model
    # model = joblib.load('/path/to/model.pkl')
    
    # Inference logic here
    # Platform handles scaling and routing
```

### Time Series Forecasting Function

```python
def main():
    from prophet import Prophet  # Add to requirements.txt
    import pandas as pd
    from flask import request
    
    # Prophet forecasting logic
    # Automatic dependency management
    # Zero infrastructure overhead
```

## Function Structure Requirements

### Directory Layout
```
functions/
└── your-function-name/
    ├── main.py           # Required: Function entry point
    └── requirements.txt  # Optional: Python dependencies
```

### Python Function Signature
```python
def main():  # Required signature - no parameters
    from flask import request  # Access HTTP request
    
    # Your logic here
    
    return {
        'status': 200,  # HTTP status code
        'body': '...',  # Response body (JSON string)
        'headers': {}   # Response headers
    }
```

### JavaScript Function Example
```javascript
// functions/my-js-function/index.js
module.exports = async function(context) {
    const { request } = context;
    
    return {
        status: 200,
        body: JSON.stringify({ message: 'Hello from JS!' }),
        headers: { 'Content-Type': 'application/json' }
    };
};
```

## Available Libraries (Pre-tested ✅)

### Data Science Stack
- **pandas 2.1.4** - Data manipulation and analysis
- **numpy 1.24.3** - Numerical computing
- **requests 2.31.0** - HTTP client
- **pydantic 2.5.0** - Data validation

### Ready for AI/ML
- **openai** - OpenAI API integration
- **prophet** - Time series forecasting
- **scikit-learn** - Machine learning toolkit
- **tensorflow** - Deep learning framework
- **torch** - PyTorch neural networks
- **transformers** - Hugging Face models
- **langchain** - LLM application framework

## Deployment Architecture

```
Git Commit → Fission Controller → Builder → Function Pod → HTTPS Endpoint
     ↓              ↓                ↓           ↓            ↓
  (60s scan)    (detects new)    (pip install) (deploys)  (live URL)
```

## Troubleshooting

### Function Not Appearing?
- Wait 60 seconds for the controller scan cycle
- Check directory structure: `/functions/name/main.py`
- Verify git commit was successful

### Import Errors?
- Add dependencies to `requirements.txt`
- Wait for builder to complete (check package status)
- Use exact versions: `pandas==2.1.4`

### 500 Errors?
- Check function signature: `def main():` (no parameters)
- Use `from flask import request` for HTTP access
- Return proper dict structure with status/body/headers

## Need Help?

- **Examples**: Check `/functions/` directory for working examples
- **Docs**: See `docs/enterprise-function-examples.md`
- **Logs**: Monitor function logs via kubectl or platform UI

## What's Next?

1. **Deploy more functions** - Each directory becomes a live endpoint
2. **Add AI models** - Prophet, scikit-learn, TensorFlow ready
3. **Integrate APIs** - OpenAI, external services, databases
4. **Monitor performance** - Built-in scaling and observability

**Welcome to zero-infrastructure AI development! 🚀**
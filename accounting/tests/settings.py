import os
DIRNAME = os.path.dirname(__file__)

DEFAULT_CHARSET = 'utf-8'

test_engine = os.environ.get("ACCOUNTING_TEST_ENGINE", "django.db.backends.sqlite3")

DATABASES = {
    'default': {
        'ENGINE': test_engine,
        'NAME': os.environ.get("ACCOUNTING_DATABASE_NAME", "accounting_test"),
        'USER': os.environ.get("ACCOUNTING_DATABASE_USER", ""),
        'PASSWORD': os.environ.get("ACCOUNTING_DATABASE_PASSWORD", ""),
        'HOST': os.environ.get("ACCOUNTING_DATABASE_HOST", "localhost"),
    }
}

if test_engine == "django.db.backends.sqlite3":
    DATABASES['default']['NAME'] = os.path.join(DIRNAME, 'accounting_test.db')
    DATABASES['default']['HOST'] = ""
elif test_engine == "django.db.backends.mysql":
    DATABASES['default']['PORT'] = os.environ.get("ACCOUNTING_DATABASE_PORT", 3306)
elif test_engine == "django.db.backends.postgresql_psycopg2":
    DATABASES['default']['PORT'] = os.environ.get("ACCOUNTING_DATABASE_PORT", 5432)

# list only Django applications required to setup a working test environment
INSTALLED_APPS = (
    # other dependencies go here 
    'accounting',
    'accounting.tests',    
)

# list only the middleware classes required to setup a working test environment
MIDDLEWARE_CLASSES = (
     # 'django.middleware.common.CommonMiddleware',
     # 'django.contrib.sessions.middleware.SessionMiddleware',
     # 'django.contrib.auth.middleware.AuthenticationMiddleware',

) 

ROOT_URLCONF = 'accounting.tests.urls'
SITE_ID = 1

# other required settings for a working test environment

##------ app-specific settings (if needed) -----##
SUBJECTIVE_MODELS = ('accounting.tests.Person', 'accounting.tests.Company')
ACCOUNT_TYPES = (
                 ('INCOME', 'Income'),
                 ('EXPENSES', 'Expenses'),
                 ('ASSET', 'Asset'),
                 ('LIABILITY', 'Liability'),
                 ('EQUITY', 'Equity'),
)

TRANSACTION_TYPES = (
                     ('INVOICE_PAYMENT', 'Payment of an invoice '),
                     ('INVOICE_COLLECTION', 'Collection of an invoice'),
)

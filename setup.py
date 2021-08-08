# coding=utf-8
"""Python Arlo setup script."""
from setuptools import setup


def readme():
    with open('README.md') as desc:
        return desc.read()


setup(

    name='pyaarlo',
    version='0.8.0a7',
    packages=['pyaarlo'],

    python_requires='>=3.6',
    install_requires=[
        'requests',
        'click',
        'pycryptodome',
        'unidecode',
        'cloudscraper>=1.2.58'
    ],

    author='Steve Herrell',
    author_email='steve.herrell@gmail.com',
    description='PyAarlo is a library that provides asynchronous access to Arlo security cameras.',
    long_description=readme(),
    long_description_content_type='text/markdown',
    license='LGPLv3+',
    keywords=[
        'arlo',
        'netgear',
        'camera',
        'home automation',
        'python',
    ],
    url='https://github.com/twrecked/pyaarlo.git',
    project_urls={
        "Bug Tracker": 'https://github.com/twrecked/pyaarlo/issues',
        "Documentation": 'https://github.com/twrecked/pyaarlo/blob/master/README.md',
        "Source Code": 'https://github.com/twrecked/pyaarlo',
    },
    classifiers=[
        'Environment :: Other Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ],

    entry_points={
        'console_scripts': [
            'pyaarlo = pyaarlo.main:main_func',
        ],
    },

    test_suite='tests',
)

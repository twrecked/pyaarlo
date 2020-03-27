# coding=utf-8
"""Python Arlo setup script."""
from setuptools import setup


def readme():
    with open('README.md') as desc:
        return desc.read()


setup(
    name='pyaarlo',
    packages=['pyaarlo'],
    version='0.6.14',
    description='Python Aarlo is a library that provides asynchronous access to Netgear Arlo cameras.',
    long_description=readme(),
    author='Steve Herrell',
    author_email='steve.herrell@gmail.com',
    url='https://github.com/twrecked/pyaarlo.git',
    license='LGPLv3+',
    include_package_data=True,
    install_requires=['requests','six','click','pycrypto'],
    test_suite='tests',
    keywords=[
        'arlo',
        'netgear',
        'camera',
        'home automation',
        'python',
        ],
    classifiers=[
        'Environment :: Other Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: ' +
        'GNU Lesser General Public License v3 or later (LGPLv3+)',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Topic :: Software Development :: Libraries :: Python Modules'
        ],
    entry_points={
        'console_scripts': [
            'pyaarlo = pyaarlo.main:main_func',
        ],
    }
)

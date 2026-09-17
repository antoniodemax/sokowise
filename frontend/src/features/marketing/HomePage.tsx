import { ArrowRight, Banknote, BarChart3, Boxes, HandCoins, MessageSquareText, Package, Receipt, ShoppingCart, Smartphone, Sparkles, Store, Users } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { BrandLockup } from '@/components/brand'
import { Badge } from '@/components/ui/badge'
import { buttonVariants } from '@/components/ui/button-variants'
import { cn } from '@/lib/utils'

import { SECTION_LINKS } from './links'
import { PublicHeader } from './PublicHeader'
import { useDocumentMeta } from './use-document-meta'

const TITLE = 'SokoWise — Simple business management for Kenyan small businesses'
const DESCRIPTION = 'Keep track of sales, stock, customers, credit and expenses in one simple place. Built around cash, M-Pesa and customer credit.'

function Section({ id, className, children, tone = 'default' }: { id?: string; className?: string; children: ReactNode; tone?: 'default' | 'card' | 'dark' }) {
  return (
    <section id={id} className={cn('scroll-mt-20 py-14 sm:py-20', tone === 'card' && 'bg-card', tone === 'dark' && 'bg-secondary text-secondary-foreground', className)}>
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">{children}</div>
    </section>
  )
}

function SectionHeading({ eyebrow, title, lead }: { eyebrow?: string; title: string; lead?: string }) {
  return (
    <div className="mb-8 max-w-2xl sm:mb-12">
      {eyebrow && <p className="mb-2 text-sm font-semibold text-primary">{eyebrow}</p>}
      <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h2>
      {lead && <p className="mt-3 text-base text-muted-foreground sm:text-lg">{lead}</p>}
    </div>
  )
}

function CtaButtons({ large, invert }: { large?: boolean; invert?: boolean }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row">
      <Link to="/register" className={cn(buttonVariants({ size: large ? 'lg' : 'default' }), invert && 'bg-card text-primary hover:bg-card/90')}>
        Get started <ArrowRight aria-hidden="true" />
      </Link>
      <Link to="/login" className={cn(buttonVariants({ variant: 'outline', size: large ? 'lg' : 'default' }), invert && 'border-secondary-foreground/30 bg-transparent text-secondary-foreground hover:bg-secondary-foreground/10')}>
        Sign in
      </Link>
    </div>
  )
}

const FEATURES = [
  { icon: ShoppingCart, title: 'Sales', text: 'Record each sale in seconds — cash, M-Pesa, credit or a split — and see where your money comes from.' },
  { icon: Package, title: 'Products & stock', text: 'Know what you have, what is running low and what needs restocking, without a stock-take every week.' },
  { icon: Users, title: 'Customers & credit', text: 'Keep a clear record of who owes you, how much, and since when. Record repayments when they pay.' },
  { icon: Receipt, title: 'Expenses', text: 'Rent, transport, airtime, licences — see where your business money is going each month.' },
  { icon: BarChart3, title: 'Business analytics', text: 'Revenue, cash collected, cost of goods, gross and net profit, best sellers and slow stock — from your own records.' },
  { icon: MessageSquareText, title: 'AI copilot', text: 'Ask plain questions like "what sold most this week?" or "who owes me money?" and get answers from your own figures.', soon: true },
] as const

const BUSINESSES = [
  { icon: Store, title: 'Dukas & general shops', text: 'Fast-moving goods, credit customers, daily cash-ups.' },
  { icon: Sparkles, title: 'Boutiques & cosmetics', text: 'Sizes, colours and stock that must not run out.' },
  { icon: HandCoins, title: 'Salons & barbers', text: 'Services and products together, M-Pesa and cash.' },
  { icon: Banknote, title: 'Restaurants & food', text: 'Daily sales, ingredients bought, running costs.' },
  { icon: Smartphone, title: 'Electronics & small retail', text: 'Higher-value items, serials in the notes, layaways.' },
  { icon: Boxes, title: 'Other small businesses', text: 'Hardware, agrovets, stationery — anything that sells.' },
] as const

const STEPS = [
  { title: 'Create your business', text: 'Register with your phone number and name your business. That is the whole set-up.' },
  { title: 'Add your products', text: 'Add products once with a price, a cost and what you have in stock. Update as you go — no need to re-enter them.' },
  { title: 'Record sales and expenses', text: 'Tap the products, choose cash, M-Pesa or credit, done. Note expenses as they happen.' },
  { title: 'Understand your business', text: 'See what sold, what it cost, what you earned and who owes you — today, this week, this month.' },
] as const

const PRINCIPLES = [
  { title: 'Simple to use', text: 'Built for a busy counter: big buttons, plain words, no training needed.' },
  { title: 'Made for small businesses', text: 'The workflows are a duka, a salon, a kiosk — not a corporate ERP cut down.' },
  { title: 'Your records stay yours', text: 'Each business has its own separate space; staff only see what the owner allows.' },
  { title: 'Everyday payment methods', text: 'Cash, M-Pesa and customer credit are first-class, not an afterthought.' },
  { title: 'Mobile-first', text: 'Works on the phone in your pocket and on a laptop at the back office.' },
] as const

export default function HomePage() {
  useDocumentMeta({ title: TITLE, description: DESCRIPTION, path: '/' })

  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:text-sm focus:shadow-md">
        Skip to content
      </a>
      <PublicHeader />
      <main id="main" className="flex-1">
        {/* Hero */}
        <Section className="pt-10 sm:pt-16">
          <div className="grid items-center gap-12 lg:grid-cols-[5fr_6fr] lg:gap-12">
            <div>
              <p className="mb-3 text-sm font-semibold text-primary">For Kenyan small businesses</p>
              <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl lg:text-5xl">Know your business. Run it with confidence.</h1>
              <p className="mt-4 max-w-xl text-base text-muted-foreground sm:text-lg">
                SokoWise keeps your sales, stock, customers, credit and expenses in one simple place — so you always know what sold, what it cost, what you earned and who owes you.
              </p>
              <div className="mt-8">
                <CtaButtons large />
              </div>
              <p className="mt-4 text-sm text-muted-foreground">Free to try. Works on your phone. Cash, M-Pesa and credit built in.</p>
            </div>
            <div className="relative mx-auto mb-10 w-full max-w-xl lg:max-w-none">
              <img src="/marketing/owner-phone-1400.webp" srcSet="/marketing/owner-phone-800.webp 800w, /marketing/owner-phone-1400.webp 1400w" sizes="(min-width: 1024px) 600px, 100vw" width={1400} height={1050} fetchPriority="high" alt="A food-stall owner in an apron smiling at his phone behind his counter." className="block aspect-[4/3] w-full rounded-2xl object-cover shadow-md" />
              <figure className="absolute -bottom-10 left-4 w-32 sm:w-40 lg:-left-6 lg:w-44">
                <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-lg">
                  <img src="/marketing/dashboard-phone.webp" width={780} height={1560} alt="The SokoWise dashboard on a phone for Karibu Mini Mart, an example business: today's revenue, cash collected and what customers owe, with products running low." className="block h-auto w-full" />
                </div>
                <figcaption className="mt-1.5 text-center text-[11px] text-muted-foreground">Example data</figcaption>
              </figure>
            </div>
          </div>
        </Section>

        {/* Features */}
        <Section id="features" tone="card">
          <SectionHeading eyebrow="What you can manage" title="Everything you need to keep your business on track." lead="One place for the daily record-keeping, and the answers that come out of it." />
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((feature) => (
              <li key={feature.title} className="rounded-xl border border-border bg-background p-5">
                <div className="flex items-start justify-between gap-3">
                  <span className="flex size-10 items-center justify-center rounded-lg bg-primary-soft text-primary" aria-hidden="true">
                    <feature.icon className="size-5" />
                  </span>
                  {'soon' in feature && feature.soon && <Badge variant="warning">Coming soon</Badge>}
                </div>
                <h3 className="mt-4 text-base font-semibold">{feature.title}</h3>
                <p className="mt-1.5 text-sm text-muted-foreground">{feature.text}</p>
                {'soon' in feature && feature.soon && <p className="mt-2 text-xs text-muted-foreground">Planned for a later release; not available yet.</p>}
              </li>
            ))}
          </ul>
        </Section>

        {/* Kenyan context */}
        <Section>
          <div className="grid items-center gap-10 lg:grid-cols-2 lg:gap-16">
            <div>
              <SectionHeading eyebrow="Local by design" title="Built around how small businesses here actually run." lead="Not a foreign template with the currency changed. The everyday realities of a Kenyan shop are the starting point." />
              <ul className="space-y-4 text-sm sm:text-base">
                {[
                  ['Cash, M-Pesa and credit on one sale', 'Split a sale between methods; note the M-Pesa code for your records.'],
                  ['Customer credit that is tracked, not remembered', 'Every "lipa baadaye" is recorded against the customer, with repayments and a limit you set.'],
                  ['Prices in KSh, to the shilling', 'No rounding surprises: figures are kept exactly, in KSh.'],
                  ['Stock that reflects what you actually sold', 'Each sale takes from stock; restocks and corrections are recorded, so the count stays honest.'],
                  ['Daily sales and monthly costs, side by side', 'See the day at a glance and the month in full — including rent, transport and airtime.'],
                ].map(([title, text]) => (
                  <li key={title} className="flex gap-3">
                    <span className="mt-1.5 size-2 shrink-0 rounded-full bg-primary" aria-hidden="true" />
                    <span>
                      <span className="font-medium">{title}</span>
                      <span className="block text-muted-foreground">{text}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <ExampleSaleCard />
          </div>
        </Section>

        {/* Who it's for */}
        <Section id="businesses" tone="card">
          <div className="grid gap-10 lg:grid-cols-[6fr_5fr] lg:gap-16">
            <div>
              <SectionHeading eyebrow="Who it's for" title="Made for the businesses on every Kenyan street." lead="If it sells products or services and needs to keep track of money, stock and customers, SokoWise fits." />
              <ul className="grid gap-4 sm:grid-cols-2">
                {BUSINESSES.map((b) => (
                  <li key={b.title} className="flex gap-4 rounded-xl border border-border bg-background p-5">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-foreground" aria-hidden="true">
                      <b.icon className="size-5" />
                    </span>
                    <div>
                      <h3 className="font-semibold">{b.title}</h3>
                      <p className="mt-1 text-sm text-muted-foreground">{b.text}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
            <div className="grid grid-cols-[3fr_2fr] gap-3 sm:gap-4 lg:self-center">
              <img src="/marketing/cook-stall-900.webp" srcSet="/marketing/cook-stall-450.webp 450w, /marketing/cook-stall-900.webp 900w" sizes="(min-width: 1024px) 300px, 55vw" width={900} height={1200} loading="lazy" alt="A street-food cook turning chapatis on a pan at her roadside stall." className="row-span-2 aspect-[3/4] h-full w-full rounded-2xl object-cover" />
              <img src="/marketing/vendor-fruit-1000.webp" srcSet="/marketing/vendor-fruit-600.webp 600w, /marketing/vendor-fruit-1000.webp 1000w" sizes="(min-width: 1024px) 200px, 40vw" width={1000} height={750} loading="lazy" alt="A fruit vendor at his stall, phone in hand, giving a thumbs-up." className="aspect-[4/3] w-full rounded-2xl object-cover" />
              <p className="flex items-center rounded-2xl bg-primary p-4 text-sm font-medium leading-snug text-primary-foreground sm:text-base">Cash, M-Pesa and trust — SokoWise keeps track of all three.</p>
            </div>
          </div>
        </Section>

        {/* How it works */}
        <Section id="how-it-works">
          <SectionHeading eyebrow="How it works" title="Up and running in an afternoon." lead="Add your products once, then keep stock and sales up to date as you run the business." />
          <ol className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((step, i) => (
              <li key={step.title} className="relative rounded-xl border border-border bg-card p-5">
                <span className="flex size-9 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground" aria-hidden="true">
                  {i + 1}
                </span>
                <h3 className="mt-4 font-semibold">
                  <span className="sr-only">Step {i + 1}: </span>
                  {step.title}
                </h3>
                <p className="mt-1.5 text-sm text-muted-foreground">{step.text}</p>
              </li>
            ))}
          </ol>
        </Section>

        {/* Product preview */}
        <Section tone="card">
          <div className="grid items-center gap-10 lg:grid-cols-[7fr_4fr] lg:gap-16">
            <div className="grid grid-cols-[1fr_auto] items-end gap-4 sm:gap-6">
              <figure className="min-w-0">
                <div className="overflow-hidden rounded-xl border border-border bg-background shadow-md">
                  <img src="/marketing/dashboard.webp" width={1280} height={800} loading="lazy" alt="The SokoWise dashboard for Karibu Mini Mart, an example business: revenue, cash collected, what customers owe, gross profit, expenses and net profit for the month, with low-stock products and top debtors." className="block h-auto w-full" />
                </div>
                <figcaption className="mt-2 text-center text-xs text-muted-foreground">The owner's dashboard, shown with example data.</figcaption>
              </figure>
              <figure className="w-28 sm:w-40">
                <div className="overflow-hidden rounded-2xl border border-border bg-background shadow-md">
                  <img src="/marketing/sell-phone.webp" width={780} height={1560} loading="lazy" alt="Taking payment for a KSh 280 sale on a phone: KSh 200 by M-Pesa with the code noted for the records, KSh 80 in cash, marked fully paid." className="block h-auto w-full" />
                </div>
                <figcaption className="mt-2 text-center text-xs text-muted-foreground">Recording a sale</figcaption>
              </figure>
            </div>
            <div>
              <SectionHeading eyebrow="The real thing" title="This is the actual SokoWise." lead="What you see here is the app itself with example data — the same screens you get after signing up, on a phone or a laptop." />
              <ul className="space-y-3 text-sm text-muted-foreground sm:text-base">
                <li>Tap products to build the sale; the total and change are worked out for you.</li>
                <li>Choose cash, M-Pesa or credit — or split between them.</li>
                <li>Stock goes down as you sell; low-stock items show up on the dashboard.</li>
                <li>The owner sees profit and expenses; staff see what they need to sell.</li>
              </ul>
              <div className="mt-8">
                <CtaButtons />
              </div>
            </div>
          </div>
        </Section>

        {/* Principles */}
        <Section>
          <SectionHeading eyebrow="Why SokoWise" title="Simple, honest and built for the counter." />
          <ul className="grid gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
            {PRINCIPLES.map((p) => (
              <li key={p.title}>
                <h3 className="font-semibold">{p.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{p.text}</p>
              </li>
            ))}
          </ul>
        </Section>

        {/* Final CTA */}
        <section className="relative isolate overflow-hidden bg-secondary py-16 text-secondary-foreground sm:py-24">
          <img src="/marketing/market-1600.webp" srcSet="/marketing/market-1000.webp 1000w, /marketing/market-1600.webp 1600w" sizes="100vw" width={1600} height={900} loading="lazy" alt="" aria-hidden="true" className="absolute inset-0 -z-20 h-full w-full object-cover opacity-40" />
          <div className="absolute inset-0 -z-10 bg-gradient-to-b from-secondary/55 via-secondary/70 to-secondary/95" aria-hidden="true" />
          <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
            <div className="mx-auto max-w-2xl text-center">
              <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">Ready to understand your business better?</h2>
              <p className="mt-3 text-base text-secondary-foreground/80 sm:text-lg">Start keeping your sales, stock, customers and expenses in one place. It takes a few minutes to set up.</p>
              <div className="mt-8 flex justify-center">
                <CtaButtons large invert />
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-border bg-card">
        <div className="mx-auto grid w-full max-w-6xl gap-8 px-4 py-10 sm:px-6 md:grid-cols-[1fr_auto]">
          <div className="max-w-sm">
            <BrandLockup className="w-48" />
            <p className="mt-4 text-sm text-muted-foreground">Sales, stock, customer credit and expenses — for Kenyan small businesses.</p>
          </div>
          <nav aria-label="Footer" className="grid grid-cols-2 gap-x-10 gap-y-2 text-sm sm:grid-cols-[auto_auto]">
            {SECTION_LINKS.map((link) => (
              <a key={link.href} href={link.href} className="inline-flex min-h-9 items-center text-muted-foreground hover:text-foreground">
                {link.label}
              </a>
            ))}
            <Link to="/login" className="inline-flex min-h-9 items-center text-muted-foreground hover:text-foreground">
              Sign in
            </Link>
            <Link to="/register" className="inline-flex min-h-9 items-center font-medium text-primary hover:underline">
              Get started
            </Link>
          </nav>
        </div>
        <div className="border-t border-border">
          <p className="mx-auto w-full max-w-6xl px-4 py-4 text-xs text-muted-foreground sm:px-6">© {new Date().getFullYear()} SokoWise. Kenya.</p>
        </div>
      </footer>
    </div>
  )
}

/** A small, clearly labelled example of one sale, built from the app's own components. */
function ExampleSaleCard() {
  const rows = [
    ['Sukari 1kg × 2', '320'],
    ['Maziwa 500ml × 3', '180'],
    ['Sabuni ya bar × 1', '140'],
  ] as const
  return (
    <figure className="mx-auto w-full max-w-sm">
      <div className="rounded-xl border border-border bg-card p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <p className="font-semibold">One sale, three ways to pay</p>
          <Badge variant="neutral">Example</Badge>
        </div>
        <dl className="mt-4 space-y-2 text-sm">
          {rows.map(([item, amount]) => (
            <div key={item} className="flex justify-between">
              <dt className="text-muted-foreground">{item}</dt>
              <dd className="tabular">KSh {amount}</dd>
            </div>
          ))}
          <div className="flex justify-between border-t border-border pt-2 font-semibold">
            <dt>Total</dt>
            <dd className="tabular">KSh 640</dd>
          </div>
        </dl>
        <ul className="mt-4 space-y-2 text-sm">
          <li className="flex items-center justify-between rounded-lg bg-muted px-3 py-2">
            <span className="flex items-center gap-2"><Banknote className="size-4 text-primary" aria-hidden="true" /> Cash</span>
            <span className="tabular">KSh 200</span>
          </li>
          <li className="flex items-center justify-between rounded-lg bg-muted px-3 py-2">
            <span className="flex items-center gap-2"><Smartphone className="size-4 text-primary" aria-hidden="true" /> M-Pesa <span className="text-xs text-muted-foreground">QTX3P9KL2M</span></span>
            <span className="tabular">KSh 300</span>
          </li>
          <li className="flex items-center justify-between rounded-lg bg-accent-soft px-3 py-2 text-accent-foreground">
            <span className="flex items-center gap-2"><HandCoins className="size-4" aria-hidden="true" /> Credit · Mama Njeri</span>
            <span className="tabular">KSh 140</span>
          </li>
        </ul>
        <p className="mt-3 text-xs text-muted-foreground">The KSh 140 is added to what Mama Njeri owes, and the stock of all three items goes down.</p>
      </div>
      <figcaption className="sr-only">An example sale paid partly in cash, partly by M-Pesa and partly on credit.</figcaption>
    </figure>
  )
}

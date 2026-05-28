import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { Bell, Check, Rocket } from 'lucide-react'

import { Button } from '#/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '#/components/ui/card'
import { Badge } from '#/components/ui/badge'
import { Input } from '#/components/ui/input'
import { Label } from '#/components/ui/label'
import { Textarea } from '#/components/ui/textarea'
import { Switch } from '#/components/ui/switch'
import { Slider } from '#/components/ui/slider'
import { Separator } from '#/components/ui/separator'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '#/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '#/components/ui/tabs'

export const Route = createFileRoute('/')({ component: Home })

function Home() {
  const [notify, setNotify] = useState(true)
  const [volume, setVolume] = useState([50])

  return (
    <div className="mx-auto max-w-3xl space-y-8 p-8">
      <header className="space-y-2">
        <div className="flex items-center gap-3">
          <h1 className="text-4xl font-bold tracking-tight">Component Showcase</h1>
          <Badge>shadcn/ui</Badge>
        </div>
        <p className="text-muted-foreground text-lg">
          A few shadcn components dropped onto the main page.
        </p>
      </header>

      <Separator />

      <div className="flex flex-wrap gap-3">
        <Button>
          <Rocket /> Primary
        </Button>
        <Button variant="secondary">Secondary</Button>
        <Button variant="outline">Outline</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="destructive">Destructive</Button>
      </div>

      <Tabs defaultValue="form">
        <TabsList>
          <TabsTrigger value="form">Form</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>

        <TabsContent value="form">
          <Card>
            <CardHeader>
              <CardTitle>Create something</CardTitle>
              <CardDescription>
                Inputs, selects, and a textarea inside a card.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input id="name" placeholder="Jane Doe" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="role">Role</Label>
                <Select>
                  <SelectTrigger id="role">
                    <SelectValue placeholder="Pick a role" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="admin">Admin</SelectItem>
                    <SelectItem value="editor">Editor</SelectItem>
                    <SelectItem value="viewer">Viewer</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="bio">Bio</Label>
                <Textarea id="bio" placeholder="Tell us a bit about yourself…" />
              </div>
            </CardContent>
            <CardFooter className="gap-2">
              <Button>
                <Check /> Save
              </Button>
              <Button variant="ghost">Cancel</Button>
            </CardFooter>
          </Card>
        </TabsContent>

        <TabsContent value="settings">
          <Card>
            <CardHeader>
              <CardTitle>Preferences</CardTitle>
              <CardDescription>Toggles and a slider.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Bell className="size-4" />
                  <Label htmlFor="notify">Notifications</Label>
                </div>
                <Switch id="notify" checked={notify} onCheckedChange={setNotify} />
              </div>
              <Separator />
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label>Volume</Label>
                  <Badge variant="secondary">{volume[0]}%</Badge>
                </div>
                <Slider
                  value={volume}
                  onValueChange={(value) =>
                    setVolume(Array.isArray(value) ? [...value] : [value])
                  }
                  max={100}
                  step={1}
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
